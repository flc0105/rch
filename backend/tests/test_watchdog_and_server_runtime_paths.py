"""Watchdog log and Server runtime roots must not change with launch CWD."""

import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from client.watchdog.client_guard_manager import ClientGuardManager
from client.watchdog.process_watchdog import get_process_watchdog_status_payload


BACKEND = Path(__file__).resolve().parents[1]
CONFIG_FILE = BACKEND / 'server' / 'config' / 'config.py'


class WatchdogLogPathsTest(unittest.TestCase):
    def test_three_log_files_share_persistent_directory(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch('client.watchdog.watchdog_paths.get_runtime_config_dir', return_value=tmp):
            manager = ClientGuardManager('device-id')
            payload = manager.get_watchdog_status_payload()
            process = get_process_watchdog_status_payload()
            paths = [payload['remote_watchdog']['log_path'],
                     payload['local_watchdog']['log_path'], process['log_path']]
            self.assertEqual([os.path.basename(path) for path in paths], [
                'client_remote_watchdog.log', 'client_local_watchdog.log', 'process_watchdog.log'])
            self.assertEqual({os.path.dirname(path) for path in paths}, {os.path.join(tmp, 'logs')})
            self.assertNotEqual(os.path.dirname(payload['local_watchdog']['heartbeat_file_path']),
                                os.path.join(tmp, 'logs'))


class ServerRuntimePathsTest(unittest.TestCase):
    @staticmethod
    def read_config(runtime_root=None):
        # Avoid creating or touching a real auth.json while reading the startup configuration.
        fake_auth = types.ModuleType('server.config.admin_auth')
        fake_auth.load_admin_auth = lambda _path: {
            'username': 'test', 'password': 'hash', 'api_token': 'secret', 'session_secret': 'secret'}
        env = dict(os.environ)
        env.pop('RCH_SERVER_RUNTIME_DIR', None)
        if runtime_root is not None:
            env['RCH_SERVER_RUNTIME_DIR'] = runtime_root
        with patch.dict(os.environ, env, clear=True), \
             patch.dict(sys.modules, {'server.config.admin_auth': fake_auth}), \
             patch('os.makedirs'):
            return runpy.run_path(str(CONFIG_FILE))

    def test_default_is_backend_runtime_independent_of_cwd(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            before = os.getcwd()
            try:
                os.chdir(temp_dir)
                cfg = self.read_config()
            finally:
                os.chdir(before)
            expected = str(BACKEND / 'runtime')
            self.assertEqual(cfg['SERVER_RUNTIME_DIR'], expected)
            self.assertEqual(cfg['RCH_DB_PATH'], os.path.join(expected, 'rch.db'))
            self.assertEqual(cfg['WEB_FILES_ROOT_DIR'], os.path.join(expected, 'web_files'))
            self.assertEqual(cfg['KEYCHAINS_ROOT_DIR'], os.path.join(expected, 'keychains'))
            self.assertEqual(cfg['SERVER_CLEANUP_LOG_ROOT_DIR'], os.path.join(expected, 'cleanup_logs'))

    def test_relative_override_is_backend_relative(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            before = os.getcwd()
            try:
                os.chdir(temp_dir)
                cfg = self.read_config('local_runtime_test')
            finally:
                os.chdir(before)
            self.assertEqual(cfg['SERVER_RUNTIME_DIR'], str(BACKEND / 'local_runtime_test'))
            self.assertEqual(cfg['RCH_DB_PATH'], str(BACKEND / 'local_runtime_test' / 'rch.db'))

    def test_absolute_override_and_agent_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg = self.read_config(temp_dir)
            self.assertEqual(cfg['SERVER_RUNTIME_DIR'], temp_dir)
            self.assertEqual(cfg['RCH_DB_PATH'], os.path.join(temp_dir, 'rch.db'))
            # Exercise the real constructors against a configured root without starting the server.
            fake_config = types.ModuleType('server.config.config')
            fake_config.SERVER_RUNTIME_DIR = temp_dir
            fake_config.SOCKET_PORT = 9999
            fake_config.WEB_PORT = 8085
            with patch.dict(sys.modules, {'server.config.config': fake_config}):
                builder_type = runpy.run_path(str(BACKEND / 'server/application/agent/agent_builder.py'))['AgentBuilder']
                api_type = runpy.run_path(str(BACKEND / 'server/application/web/agent_api.py'))['WebAgentApi']
                builder = builder_type()
                api = api_type(builder, None)
                self.assertEqual(builder.output_dir, os.path.join(temp_dir, 'agent_output'))
                self.assertEqual(api.logs_dir, os.path.join(temp_dir, 'logs'))


if __name__ == '__main__':
    unittest.main()
