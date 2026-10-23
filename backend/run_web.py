import threading

import uvicorn
from werkzeug.serving import make_server

from server.config.config import SERVER_RUNTIME_DIR, SOCKET_ADDR, WEB_FILE_TRANSFER_PORT, WEB_HOST, WEB_PORT
from rchserver import Server
from core.utils.logger import logger
from server.web.asgi import create_asgi_app
from server.web.file_transfer_app import create_file_transfer_app
from server.runtime.server_logging import install_server_file_logging, attach_uvicorn_file_logging


def start_file_transfer_server(server):
    app = create_file_transfer_app(server)
    transfer_server = make_server(WEB_HOST, WEB_FILE_TRANSFER_PORT, app, threaded=True)
    threading.Thread(
        target=transfer_server.serve_forever,
        name='file-transfer-http-server',
        daemon=True,
    ).start()
    logger.info('File transfer HTTP listening on %s:%s', WEB_HOST, WEB_FILE_TRANSFER_PORT)
    return transfer_server


def main():
    file_handler = install_server_file_logging(SERVER_RUNTIME_DIR)
    server = Server(SOCKET_ADDR)

    threading.Thread(target=server.serve, daemon=True).start()
    threading.Thread(target=server.heartbeat_loop, daemon=True).start()

    transfer_server = start_file_transfer_server(server)
    app = create_asgi_app(server)
    server.schedule_startup_cleanup()
    try:
        config = uvicorn.Config(app, host=WEB_HOST, port=WEB_PORT, log_level='info')
        attach_uvicorn_file_logging(file_handler)
        uvicorn.Server(config).run()
    finally:
        transfer_server.shutdown()


if __name__ == '__main__':
    main()
