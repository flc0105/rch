import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

import requests

from .backends import create_notification_backend
from .config import default_config_path, default_state_path, load_config, write_example_config
from .sse import NotificationSseClient, SseAuthenticationError
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


def _run_stream(config, state, backend, stop_event):
    client = NotificationSseClient(url=config.stream_url, token=config.token)
    delay = config.reconnect_initial_seconds

    while not stop_event.is_set():
        cursor = state.last_event_id
        logger.info('Connecting to %s%s', config.stream_url, f' after {cursor}' if cursor else '')
        try:
            for event in client.events(cursor):
                if stop_event.is_set():
                    return 0
                if event.event == 'ping':
                    continue
                if event.event == 'reset':
                    logger.warning('Server no longer has the local SSE cursor; continuing from live events')
                    state.clear()
                    continue
                if event.event != 'notification':
                    continue

                notification = event.json()
                notification_id = str(notification.get('id') or event.event_id or '').strip()
                if not notification_id:
                    logger.warning('Ignoring notification without an id')
                    continue

                backend.notify(notification)
                state.update(notification_id)
                logger.info('Notification delivered: %s', notification.get('title') or notification_id)
                delay = config.reconnect_initial_seconds

            if stop_event.is_set():
                return 0
            raise RuntimeError('SSE stream ended')
        except SseAuthenticationError:
            logger.error('Authentication failed. Check the notifier token in the config.')
            return 2
        except requests.RequestException as exc:
            logger.warning('SSE connection error: %s', exc)
        except Exception as exc:
            logger.warning('Notifier stream/delivery error: %s', exc, exc_info=logger.isEnabledFor(logging.DEBUG))

        if stop_event.wait(delay):
            return 0
        delay = min(config.reconnect_max_seconds, max(config.reconnect_initial_seconds, delay * 2))

    return 0


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
    stop_event = threading.Event()

    def stop_handler(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    logger.info('RCH Desktop Notifier started; backend=%s', getattr(backend, 'active_mode', 'unknown'))
    return _run_stream(config, state, backend, stop_event)
