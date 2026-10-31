"""Mirror Server logging to a bounded runtime log without changing console output."""

import logging
import os
from logging.handlers import RotatingFileHandler


SERVER_LOG_FILENAME = 'server.log'
SERVER_LOG_MAX_BYTES = 10 * 1024 * 1024
SERVER_LOG_BACKUP_COUNT = 5


def install_server_file_logging(runtime_dir):
    """Install one shared file handler before starting the Server's workers."""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if getattr(handler, '_rch_server_runtime_log', False):
            return handler

    handler = RotatingFileHandler(
        os.path.join(runtime_dir, SERVER_LOG_FILENAME),
        maxBytes=SERVER_LOG_MAX_BYTES,
        backupCount=SERVER_LOG_BACKUP_COUNT,
        encoding='utf-8',
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(levelname)s %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    ))
    handler._rch_server_runtime_log = True
    root_logger.addHandler(handler)
    return handler
