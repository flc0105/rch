"""Optional per-process Client main log, independent of stdout/stderr."""

import logging
import os
import shutil
import tempfile
from logging.handlers import RotatingFileHandler

from client.runtime.temp_workspace import get_temp_category_dir


CLIENT_LOG_FILENAME = 'client.log'
CLIENT_LOG_MAX_BYTES = 10 * 1024 * 1024
CLIENT_LOG_BACKUP_COUNT = 5


def _report_file_log_failure(exc):
    try:
        print(f'Client file logging unavailable: {exc}', flush=True)
    except Exception:
        pass


class _ClientRotatingFileHandler(RotatingFileHandler):
    """Do not let later file-write or rotation errors interrupt Client commands."""

    _failure_reported = False

    def handleError(self, record):
        if not self._failure_reported:
            self._failure_reported = True
            _report_file_log_failure('write or rotation failed; continuing with console logging')


def get_client_log_path() -> str:
    """Return only the log file for a successfully installed main-process handler."""
    for handler in logging.getLogger().handlers:
        if getattr(handler, '_rch_client_main_log', False):
            return os.path.abspath(handler.baseFilename)
    return ''


def install_client_file_logging() -> str:
    """Start optional file mirroring; startup must succeed even if temp is unwritable."""
    existing = get_client_log_path()
    if existing:
        return existing

    session_dir = ''
    handler = None
    try:
        log_root = get_temp_category_dir('client_logs', private=True)
        session_dir = tempfile.mkdtemp(prefix='client_', dir=log_root)
        log_path = os.path.join(session_dir, CLIENT_LOG_FILENAME)
        handler = _ClientRotatingFileHandler(
            log_path,
            maxBytes=CLIENT_LOG_MAX_BYTES,
            backupCount=CLIENT_LOG_BACKUP_COUNT,
            encoding='utf-8',
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(
            '[%(asctime)s] %(levelname)s %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        ))
        handler._rch_client_main_log = True
        logging.getLogger().addHandler(handler)
        return log_path
    except Exception as exc:
        if handler is not None:
            try:
                handler.close()
            except Exception:
                pass
        if session_dir:
            shutil.rmtree(session_dir, ignore_errors=True)
        _report_file_log_failure(exc)
        return ''
