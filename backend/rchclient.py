import json
import os
import sys
import threading
import time
import traceback

from client.bootstrap.client_app import Client
from client.config.config import SERVER_ADDR
from client.watchdog.watchdog_process import run_watchdog_worker_from_argv
from client.watchdog.process_watchdog import (
    ProcessWatchdogManager, run_process_watchdog_worker_from_argv,
)
from client.config import runtime_config
from client.runtime.client_logging import install_client_file_logging
from core.utils.logger import logger


def _pop_argv_value(flag_name: str) -> str:
    args = sys.argv[1:]
    for index, arg in enumerate(list(args)):
        if arg == flag_name and index + 1 < len(args):
            value = args[index + 1]
            del sys.argv[index + 1:index + 3]
            return str(value or '').strip()
        if arg.startswith(f'{flag_name}='):
            value = arg.split('=', 1)[1]
            del sys.argv[index + 1]
            return str(value or '').strip()
    return ''


def _run_elevated_detached_bootstrap():
    """Create the elevated Client as a real detached process, then let the bootstrap exit."""
    try:
        sys.argv.remove('--elevated-detached-bootstrap')
    except ValueError:
        pass

    from client.runtime.client_util import spawn_new_instance
    spawn_new_instance()


def _write_update_ready_marker(file_path: str, client: Client):
    target_path = os.path.abspath(str(file_path or '').strip()) if file_path else ''
    if not target_path:
        return

    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    temp_path = f'{target_path}.tmp'
    payload = {
        'pid': os.getpid(),
        'client_id': client.client_id,
        'client_revision': str((client.info or {}).get('client_revision') or ''),
    }
    with open(temp_path, 'w', encoding='utf-8') as file_obj:
        json.dump(payload, file_obj)
    os.replace(temp_path, target_path)


def _activate_watchdog_after_update_acceptance(ready_file, manager):
    """Do not supervise an update candidate until the old Client accepts it."""
    accepted = f'{ready_file}.accepted'
    acknowledged = f'{ready_file}.adopted'
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        if os.path.isfile(accepted):
            result = {'ok': True}
            try:
                if runtime_config.PROCESS_WATCHDOG_ENABLED:
                    manager.start()
            except Exception as exc:
                result = {'ok': False, 'error': str(exc)}
                logger.error('Failed to activate updated Client process watchdog', exc_info=True)
            try:
                with open(acknowledged, 'w', encoding='utf-8') as file_obj:
                    json.dump(result, file_obj)
            except OSError:
                logger.error('Failed to acknowledge update watchdog activation', exc_info=True)
            return
        time.sleep(0.1)


def main():
    if '--elevated-detached-bootstrap' in sys.argv[1:]:
        _run_elevated_detached_bootstrap()
        return
    if '--watchdog-worker' in sys.argv[1:]:
        run_watchdog_worker_from_argv()
        sys.exit(0)
    if '--process-watchdog-worker' in sys.argv[1:]:
        run_process_watchdog_worker_from_argv()
        sys.exit(0)

    update_ready_file = _pop_argv_value('--update-ready-file')
    install_client_file_logging()
    process_watchdog = ProcessWatchdogManager()
    if not update_ready_file and runtime_config.PROCESS_WATCHDOG_ENABLED:
        try:
            process_watchdog.start()
        except Exception:
            logger.error('Failed to start Client process watchdog', exc_info=True)

    client = None
    try:
        client = Client(SERVER_ADDR, process_watchdog_manager=process_watchdog)
        client.connect()
        _write_update_ready_marker(update_ready_file, client)
        if update_ready_file:
            threading.Thread(
                target=_activate_watchdog_after_update_acceptance,
                args=(update_ready_file, process_watchdog),
                name='ProcessWatchdogUpdateActivation', daemon=True,
            ).start()
        client.wait()
    except KeyboardInterrupt:
        if client is not None:
            client.server.report_session_end('client_exit')
        process_watchdog.stop()
        if client is not None:
            client.guard_manager.stop()
        sys.exit(0)
    except Exception as e:
        if client is not None:
            client.server.report_session_end(
                'client_error', summary=f'{type(e).__name__}: {e}',
                traceback_text=traceback.format_exc(),
            )
            client.guard_manager.stop()
        logger.error(e, exc_info=True)


if __name__ == '__main__':
    main()
