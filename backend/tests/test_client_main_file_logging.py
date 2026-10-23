"""Client main log is optional and independent from console redirection."""
import contextlib
import io
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from client.runtime import client_logging


class ClientMainFileLoggingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.category = os.path.join(self.temp.name, 'rch_client_temp', 'client_logs')

    def tearDown(self):
        for handler in list(logging.getLogger().handlers):
            if getattr(handler, '_rch_client_main_log', False):
                logging.getLogger().removeHandler(handler)
                handler.close()

    def install(self):
        with patch('client.runtime.client_logging.get_temp_category_dir', return_value=self.category):
            os.makedirs(self.category, exist_ok=True)
            return client_logging.install_client_file_logging()

    def test_file_mirrors_console_log_and_reconnect_reuses_path(self):
        from core.utils.logger import logger
        original = list(logger.handlers)
        path = self.install()
        self.assertEqual(path, client_logging.get_client_log_path())
        self.assertEqual(self.install(), path)
        logger.info('client-main-log-marker')
        self.assertEqual(Path(path).read_text(encoding='utf-8').count('client-main-log-marker'), 1)
        self.assertEqual(logger.handlers, original)
        self.assertEqual(len([h for h in logging.getLogger().handlers if getattr(h, '_rch_client_main_log', False)]), 1)
        if os.name != 'nt':
            self.assertEqual(os.stat(os.path.dirname(path)).st_mode & 0o777, 0o700)

    def test_failure_does_not_raise_or_report_nonexistent_log_path(self):
        buf = io.StringIO()
        with patch('client.runtime.client_logging.get_temp_category_dir', side_effect=PermissionError('no write permission')):
            with contextlib.redirect_stdout(buf):
                self.assertEqual(client_logging.install_client_file_logging(), '')
        self.assertIn('Client file logging unavailable:', buf.getvalue())
        self.assertEqual(client_logging.get_client_log_path(), '')

    def test_file_open_failure_is_nonblocking_and_removes_empty_instance_dir(self):
        buf = io.StringIO()
        with patch('client.runtime.client_logging.get_temp_category_dir', return_value=self.category), \
             patch('client.runtime.client_logging._ClientRotatingFileHandler', side_effect=PermissionError('cannot open log')):
            os.makedirs(self.category, exist_ok=True)
            with contextlib.redirect_stdout(buf):
                self.assertEqual(client_logging.install_client_file_logging(), '')
        self.assertIn('cannot open log', buf.getvalue())
        self.assertEqual(os.listdir(self.category), [])

    def test_log_file_survives_stdout_and_stderr_redirection(self):
        from core.utils.logger import logger
        path = self.install()
        with open(os.devnull, 'w') as null_output, contextlib.redirect_stdout(null_output), \
             contextlib.redirect_stderr(null_output):
            logger.info('client-file-independent-of-stdio')
        self.assertIn('client-file-independent-of-stdio', Path(path).read_text(encoding='utf-8'))

    def test_automatic_rotation_and_bounded_backups(self):
        with patch.object(client_logging, 'CLIENT_LOG_MAX_BYTES', 210), \
             patch.object(client_logging, 'CLIENT_LOG_BACKUP_COUNT', 2):
            path = self.install()
        log = logging.getLogger('rch-test-client-rotation')
        prev = log.level
        log.setLevel(logging.INFO)
        try:
            for i in range(30):
                log.info('client-rotation-line-%02d %s', i, 'X' * 80)
        finally:
            log.setLevel(prev)
        self.assertTrue(Path(path + '.1').is_file())
        self.assertTrue(Path(path + '.2').is_file())
        self.assertFalse(Path(path + '.3').exists())

    def test_runtime_write_failure_is_reported_once_and_does_not_propagate(self):
        path = self.install()
        handler = next(h for h in logging.getLogger().handlers if getattr(h, '_rch_client_main_log', False))
        out = io.StringIO()
        with patch.object(handler, 'doRollover', side_effect=OSError('disk full')), \
             patch.object(handler, 'shouldRollover', return_value=True), contextlib.redirect_stdout(out):
            for _ in range(2):
                logging.getLogger('rch-test-log-error').warning('failed write')
        self.assertEqual(out.getvalue().count('Client file logging unavailable:'), 1)
        self.assertTrue(os.path.exists(path))

    def test_handshake_reports_only_installed_path(self):
        from client.runtime.client_info_builder import ClientInfoBuilder
        from types import SimpleNamespace
        fake = SimpleNamespace(os_type='linux', os_alias='linux', os_full='Linux', os_name='Linux',
                               os_version='1', arch='x86_64', manufacturer='', model='',
                               hostname='test', machine_id='m', fingerprint_basis='fingerprint')
        with patch('client.runtime.client_info_builder.get_local_identity', return_value=fake), \
             patch('client.runtime.client_info_builder.get_executable_path', return_value='python3'), \
             patch('client.runtime.client_info_builder.check_privilege', return_value='user'), \
             patch('client.runtime.client_info_builder.get_system_paths', return_value={}), \
             patch('client.runtime.client_info_builder._get_client_revision_manifest', return_value={}):
            builder = ClientInfoBuilder('c1')
            with patch.object(builder, '_build_process_info', return_value={'username':'user','process_name':'python'}):
                self.assertEqual(builder.build()['client_log_path'], '')
                path = self.install()
                self.assertEqual(builder.build()['client_log_path'], path)

    def test_server_serializes_handshake_extra(self):
        from server.models.session_info import SessionInfo
        from server.application.connection.connection_service import WebConnectionService
        from types import SimpleNamespace
        session = SimpleNamespace(
            session_info=SessionInfo.from_dict({'id': 'c1', 'client_log_path': '/tmp/client.log'}),
            context=SimpleNamespace(connected_at='', disconnected_at='', last_seen_at='',
                last_heartbeat_sent_at='', last_heartbeat_ack_at='', last_rtt_ms=None),
        )
        service = WebConnectionService.__new__(WebConnectionService)
        self.assertEqual(service.serialize_connection(session)['client_log_path'], '/tmp/client.log')
