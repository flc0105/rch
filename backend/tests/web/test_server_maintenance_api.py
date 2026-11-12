"""Web maintenance: admin API token authorization and one-shot acceptance."""

import unittest
from unittest.mock import patch

from flask import Flask

from server.runtime.server_lifecycle import ServerLifecycle
from server.web.auth_guard import WebAuthGuard
from server.web.routes.server_maintenance import create_server_maintenance_blueprint


class FakeServer:
    def __init__(self, *, foreground=False, transfers=False, jobs=False):
        class Connection:
            session_info = type('Info', (), {'client_id': 'client-1'})()
            def get_foreground_task(self):
                return {'command': 'sleep 20'} if foreground else None
        class Connections:
            def all(self):
                return [Connection()]
        class TransferApi:
            def list_transfers(self):
                return {'active': [{'state': 'running'}] if transfers else []}
        class JobApi:
            def list_background_jobs(self, client_id):
                return [{'state': 'running'}] if jobs else []
        self.connections = Connections()
        self.web_service = type('WebService', (), {
            'transfer_api': TransferApi(), 'job_api': JobApi(),
        })()


class ServerMaintenanceApiTests(unittest.TestCase):
    def setUp(self):
        self.lifecycle = ServerLifecycle()
        self.app = Flask(__name__)
        self.app.secret_key = 'test-secret'
        self.app.register_blueprint(create_server_maintenance_blueprint(FakeServer(), self.lifecycle))
        self.client = self.app.test_client()

    def test_non_admin_token_cannot_act_or_read_maintenance_status(self):
        headers = {'Authorization': 'Bearer not-an-admin-token'}
        self.assertEqual(self.client.post('/api/server/restart', headers=headers).status_code, 403)
        self.assertEqual(self.client.get('/api/server/maintenance', headers=headers).status_code, 403)

    def test_admin_session_without_api_token_cannot_access_maintenance(self):
        with patch.object(WebAuthGuard, 'has_valid_session', return_value=True), \
                patch.object(WebAuthGuard, 'has_valid_static_token', return_value=False):
            self.assertEqual(self.client.get('/api/server/maintenance').status_code, 403)
            self.assertEqual(self.client.post('/api/server/shutdown').status_code, 403)
            self.assertEqual(self.client.post('/api/server/restart', headers={
                'Origin': 'http://localhost', 'Sec-Fetch-Site': 'same-origin',
            }).status_code, 403)
            self.assertIsNone(self.lifecycle.action)

    def test_admin_token_accepts_requests_regardless_of_browser_origin(self):
        with patch.object(WebAuthGuard, 'has_valid_session', return_value=False), \
                patch.object(WebAuthGuard, 'has_valid_static_token', return_value=True):
            response = self.client.post('/api/server/shutdown', headers={
                'Origin': 'https://another.example',
                'Referer': 'https://another.example/action',
                'Sec-Fetch-Site': 'cross-site',
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.lifecycle.action, 'shutdown')
            response.close()

    def test_real_api_token_header_works_without_session(self):
        with patch('server.web.auth_guard.server_config.ADMIN_API_TOKEN', 'admin-test-secret'), \
                patch.object(WebAuthGuard, 'has_valid_session', return_value=False):
            for header in ('Authorization', 'X-Auth-Token', 'X-API-Token'):
                value = 'Bearer admin-test-secret' if header == 'Authorization' else 'admin-test-secret'
                response = self.client.get('/api/server/maintenance', headers={header: value})
                self.assertEqual(response.status_code, 200, header)
            self.assertEqual(self.client.get('/api/server/maintenance', headers={
                'Authorization': 'Bearer client-token',
            }).status_code, 403)

    def test_admin_token_can_request_restart_once(self):
        with patch.object(WebAuthGuard, 'has_valid_session', return_value=False), \
                patch.object(WebAuthGuard, 'has_valid_static_token', return_value=True):
            old_id = self.client.get('/api/server/maintenance').json['data']['instance_id']
            self.assertEqual(old_id, self.lifecycle.instance_id)
            response = self.client.post('/api/server/restart')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.client.post('/api/server/shutdown').status_code, 409)
            response.close()

    def test_busy_operations_block_lifecycle_actions(self):
        with patch.object(WebAuthGuard, 'has_valid_static_token', return_value=True):
            for category in ['foreground', 'transfers', 'jobs']:
                lifecycle = ServerLifecycle()
                app = Flask(category)
                app.secret_key = 'test-secret'
                app.register_blueprint(create_server_maintenance_blueprint(FakeServer(**{category: True}), lifecycle))
                client = app.test_client()
                response = client.post('/api/server/restart')
                self.assertEqual(response.status_code, 409, category)
                self.assertIsNone(lifecycle.action)

    def test_invalid_action_is_not_registered(self):
        with patch.object(WebAuthGuard, 'has_valid_static_token', return_value=True):
            response = self.client.post('/api/server/reload')
            self.assertEqual(response.status_code, 404)
            self.assertIsNone(self.lifecycle.action)


if __name__ == '__main__':
    unittest.main()
