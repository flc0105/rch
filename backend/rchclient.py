import sys
import traceback

from client.app.client import Client
from client.config.config import SERVER_ADDR
from client.config.feature_config import resolve_features
from client.config import runtime_config
from client.app.logging import install_client_file_logging
from core.utils.logger import logger


def main():
    if '--watchdog-worker' in sys.argv[1:]:
        from client.watchdog.watchdog_process import run_watchdog_worker_from_argv
        run_watchdog_worker_from_argv()
        sys.exit(0)
    if '--process-recovery-watchdog-worker' in sys.argv[1:]:
        from client.watchdog.process_recovery_watchdog import run_process_recovery_watchdog_worker_from_argv
        run_process_recovery_watchdog_worker_from_argv()
        sys.exit(0)

    install_client_file_logging()
    features = resolve_features()
    process_recovery_watchdog = None
    if features['watchdog']:
        from client.watchdog.process_recovery_watchdog import ProcessRecoveryWatchdogManager
        process_recovery_watchdog = ProcessRecoveryWatchdogManager()
    from client.update.signals import is_update_candidate, set_recovery_manager
    set_recovery_manager(process_recovery_watchdog)
    if (process_recovery_watchdog is not None and runtime_config.PROCESS_RECOVERY_WATCHDOG_ENABLED
            and not is_update_candidate()):
        try:
            process_recovery_watchdog.start()
        except Exception:
            logger.error('Failed to start Client Process Recovery Watchdog', exc_info=True)

    client = None
    try:
        client = Client(SERVER_ADDR, process_recovery_watchdog_manager=process_recovery_watchdog)
        client.connect_initial()
        client.wait()
    except KeyboardInterrupt:
        if client is not None:
            client.server.report_session_end('client_exit')
        if process_recovery_watchdog is not None:
            process_recovery_watchdog.stop()
        if client is not None:
            if client.watchdog_manager is not None:
                client.watchdog_manager.stop()
        sys.exit(0)
    except Exception as e:
        if client is not None:
            client.server.report_session_end(
                'client_error', summary=f'{type(e).__name__}: {e}',
                traceback_text=traceback.format_exc(),
            )
            if client.watchdog_manager is not None:
                client.watchdog_manager.stop()
        logger.error(e, exc_info=True)


if __name__ == '__main__':
    main()
