"""Regression tests for additional Server runtime logging."""

import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from server.runtime.server_logging import (
    attach_uvicorn_file_logging,
    install_server_file_logging,
)


class ServerRuntimeFileLoggingTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.handler = None

    def tearDown(self):
        if self.handler is not None:
            for name in ('', 'uvicorn', 'uvicorn.access'):
                target = logging.getLogger(name)
                if self.handler in target.handlers:
                    target.removeHandler(self.handler)
            self.handler.close()

    def test_mirrors_project_uvicorn_and_access_without_replacing_console_handlers(self):
        from core.utils.logger import logger as console_logger
        import uvicorn

        existing_console_handlers = list(console_logger.handlers)
        self.handler = install_server_file_logging(self.temp_dir.name)

        async def asgi_app(scope, receive, send):
            pass

        uvicorn.Config(asgi_app, log_level='info')
        uvicorn_console_handlers = list(logging.getLogger('uvicorn').handlers)
        uvicorn_access_handlers = list(logging.getLogger('uvicorn.access').handlers)
        attach_uvicorn_file_logging(self.handler)
        attach_uvicorn_file_logging(self.handler)

        console_logger.info('runtime-project-log-marker')
        logging.getLogger('uvicorn.error').info('runtime-uvicorn-log-marker')
        logging.getLogger('uvicorn.access').info(
            '%s - "%s %s HTTP/%s" %d',
            '127.0.0.1:55000', 'GET', '/runtime-access-log-marker', '1.1', 200,
        )
        logging.getLogger('werkzeug').warning('runtime-werkzeug-log-marker')
        self.handler.flush()

        contents = (Path(self.temp_dir.name) / 'server.log').read_text(encoding='utf-8')
        for marker in ('runtime-project-log-marker', 'runtime-uvicorn-log-marker',
                       'runtime-access-log-marker', 'runtime-werkzeug-log-marker'):
            self.assertEqual(contents.count(marker), 1, marker)
        self.assertEqual(console_logger.handlers, existing_console_handlers)
        for existing in uvicorn_console_handlers:
            self.assertIn(existing, logging.getLogger('uvicorn').handlers)
        for existing in uvicorn_access_handlers:
            self.assertIn(existing, logging.getLogger('uvicorn.access').handlers)

    def test_rotates_by_size_and_does_not_duplicate_on_repeat_install(self):
        with patch('server.runtime.server_logging.SERVER_LOG_MAX_BYTES', 300), \
             patch('server.runtime.server_logging.SERVER_LOG_BACKUP_COUNT', 2):
            self.handler = install_server_file_logging(self.temp_dir.name)
            self.assertIs(self.handler, install_server_file_logging(self.temp_dir.name))
            test_logger = logging.getLogger('server.runtime.logging-test')
            original_level = test_logger.level
            test_logger.setLevel(logging.INFO)
            try:
                for index in range(40):
                    test_logger.info('rotating-entry-%02d %s', index, 'A' * 80)
            finally:
                test_logger.setLevel(original_level)
            self.handler.flush()

        root = Path(self.temp_dir.name)
        self.assertTrue((root / 'server.log').exists())
        self.assertTrue((root / 'server.log.1').exists())
        self.assertTrue((root / 'server.log.2').exists())
        self.assertFalse((root / 'server.log.3').exists())
        self.assertLessEqual(os.path.getsize(root / 'server.log'), 300)
        self.assertIn('rotating-entry-39', (root / 'server.log').read_text(encoding='utf-8'))

    def test_redirected_stdout_and_stderr_do_not_disable_file_log(self):
        script = (
            'import logging, sys; '
            'from server.runtime.server_logging import install_server_file_logging; '
            'install_server_file_logging(sys.argv[1]); '
            'logging.getLogger("redirected-test").warning("redirected-log-marker")'
        )
        result = subprocess.run(
            [sys.executable, '-c', script, self.temp_dir.name],
            cwd=str(Path(__file__).resolve().parents[1]),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn(
            'redirected-log-marker',
            (Path(self.temp_dir.name) / 'server.log').read_text(encoding='utf-8'),
        )

    def test_unwritable_log_target_raises_instead_of_silently_disabling_logging(self):
        with tempfile.TemporaryDirectory() as missing_parent:
            with self.assertRaises(FileNotFoundError):
                install_server_file_logging(os.path.join(missing_parent, 'not-created'))


if __name__ == '__main__':
    unittest.main()
