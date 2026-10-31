import asyncio
import threading

from werkzeug.serving import make_server

from server.config.config import SERVER_RUNTIME_DIR, SOCKET_ADDR, WEB_HOST, WEB_PORT, WEB_WS_PORT
from rchserver import Server
from core.utils.logger import logger
from server.web.app import create_app
from server.web.ws_server import run_ws_server
from server.runtime.server_logging import install_server_file_logging


def main():
    install_server_file_logging(SERVER_RUNTIME_DIR)
    server = Server(SOCKET_ADDR)
    threading.Thread(target=server.serve, daemon=True).start()
    threading.Thread(target=server.heartbeat_loop, daemon=True).start()

    flask_app = create_app(server)
    ready = threading.Event()
    ws_failure = []
    def run_ws():
        try:
            asyncio.run(run_ws_server(server, flask_app, ready))
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
    try:
        http_server.serve_forever()
    finally:
        http_server.shutdown()


if __name__ == '__main__':
    main()
