import asyncio
import os
import sys
import threading
from pathlib import Path

from werkzeug.serving import make_server

from server.config.config import SERVER_RUNTIME_DIR, SOCKET_ADDR, WEB_HOST, WEB_PORT, WEB_WS_PORT
from rchserver import Server
from core.utils.logger import logger
from server.web.app import create_app
from server.web.ws_server import run_ws_server
from server.runtime.server_lifecycle import ServerLifecycle
from server.runtime.server_logging import install_server_file_logging


def main():
    install_server_file_logging(SERVER_RUNTIME_DIR)
    lifecycle = ServerLifecycle()
    stop_event = threading.Event()
    server = Server(SOCKET_ADDR)
    threading.Thread(target=server.serve, daemon=True).start()
    heartbeat_thread = threading.Thread(target=server.heartbeat_loop, args=(stop_event,), daemon=True)
    heartbeat_thread.start()

    flask_app = create_app(server, lifecycle)
    ready = threading.Event()
    ws_failure = []
    def run_ws():
        try:
            asyncio.run(run_ws_server(server, flask_app, ready, stop_event))
        except Exception as exc:
            ws_failure.append(exc)
            ready.set()
    ws_thread = threading.Thread(
        target=run_ws,
        name='websocket-server', daemon=True,
    )
    ws_thread.start()
    if not ready.wait(10) or ws_failure:
        raise RuntimeError('WebSocket listener failed to start') from (ws_failure[0] if ws_failure else None)
    logger.info('WebSocket listening on %s:%s', WEB_HOST, WEB_WS_PORT)
    server.schedule_startup_cleanup()
    http_server = make_server(WEB_HOST, WEB_PORT, flask_app, threaded=True)
    logger.info('Flask HTTP and file transfer listening on %s:%s', WEB_HOST, WEB_PORT)

    # Werkzeug shutdown must be invoked from another thread while the main
    # thread is inside serve_forever. The API activates only after its response closes.
    def await_maintenance():
        lifecycle.wait()
        http_server.shutdown()
    threading.Thread(target=await_maintenance, name='server-maintenance', daemon=True).start()

    try:
        http_server.serve_forever()
    finally:
        http_server.shutdown()
        http_server.server_close()
        stop_event.set()
        server.listener_manager.stop_all()
        for connection in server.connections.all():
            try:
                connection.close()
            except Exception:
                logger.exception('Failed to close a client connection during shutdown')
        ws_thread.join(timeout=10)
        heartbeat_thread.join(timeout=2)

    if lifecycle.action == 'restart':
        entry = str(Path(__file__).resolve())
        logger.info('Restarting RCH Server through %s', entry)
        os.execv(sys.executable, [sys.executable, entry, *sys.argv[1:]])


if __name__ == '__main__':
    main()
