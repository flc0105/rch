import argparse
import logging
import platform
import signal
import threading
from pathlib import Path

from .backends import create_notification_backend
from .config import default_config_path, default_state_path, load_config, write_example_config
from .runtime import NotificationStreamRuntime
from .state import CursorState


logger = logging.getLogger('rch_notifier')


def _build_parser():
    parser = argparse.ArgumentParser(description='RCH Desktop Notifier')
    parser.add_argument('--config', type=Path, default=None, help='Path to notifier config JSON')
    parser.add_argument('--init-config', action='store_true', help='Create a starter config and exit')
    parser.add_argument('--test-notification', action='store_true', help='Show a local test notification and exit')
    parser.add_argument('--verbose', action='store_true', help='Enable debug logging')
    return parser


def _configure_logging(verbose: bool):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )


def _run_headless(runtime: NotificationStreamRuntime) -> int:
    def stop_handler(_signum, _frame):
        runtime.stop()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    return runtime.run()


def _run_macos_menu(config, backend, runtime: NotificationStreamRuntime) -> int:
    from .menu_bar_macos import MacOSMenuBar

    menu = MacOSMenuBar(server_url=config.server_url, backend=backend, runtime=runtime)
    runtime.set_status_callback(menu.update_connection)

    worker = threading.Thread(
        target=runtime.run,
        name='rch-notifier-sse',
        daemon=True,
    )

    def stop_handler(_signum, _frame):
        menu.request_quit()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    worker.start()
    try:
        menu.run()
    finally:
        runtime.stop()
        worker.join(timeout=5)

    return runtime.exit_code


def main(argv=None):
    args = _build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    config_path = (args.config or default_config_path()).expanduser().resolve()

    if args.init_config:
        try:
            path = write_example_config(config_path)
        except FileExistsError as exc:
            logger.error('%s', exc)
            return 1
        print(path)
        return 0

    if not config_path.exists():
        logger.error('Config not found: %s', config_path)
        logger.error('Run with --init-config, then set server_url and token.')
        return 1

    try:
        config = load_config(config_path)
        backend = create_notification_backend(config.backend, sound=config.sound)
        backend.start()
    except Exception as exc:
        logger.error('Notifier startup failed: %s', exc, exc_info=args.verbose)
        return 1

    if args.test_notification:
        backend.notify({
            'id': 'local-test',
            'type': 'info',
            'title': 'RCH Notifier',
            'message': 'Desktop notification test succeeded.',
        })
        logger.info('Test notification submitted using %s', getattr(backend, 'active_mode', 'unknown'))
        return 0

    state = CursorState(default_state_path(config_path))
    runtime = NotificationStreamRuntime(config=config, state=state, backend=backend)
    logger.info('RCH Desktop Notifier started; backend=%s', getattr(backend, 'active_mode', 'unknown'))

    if platform.system().lower() == 'darwin':
        try:
            return _run_macos_menu(config, backend, runtime)
        except Exception as exc:
            logger.error('macOS menu bar failed to start: %s', exc, exc_info=args.verbose)
            return 1

    return _run_headless(runtime)
