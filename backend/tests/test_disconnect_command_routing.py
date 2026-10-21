"""The Disconnect UI's HTTP route must send the registered Client session command."""
from types import SimpleNamespace

from flask import Flask

from rchserver import Server
from server.web.routes.connections import create_connections_blueprint


def test_disconnect_api_dispatches_kill_instance():
    sent = []
    session = SimpleNamespace(send_command=lambda command: sent.append(command))
    server = Server.__new__(Server)
    server.connections = SimpleNamespace(get_by_client_id=lambda client_id: session if client_id == 'device-1' else None)
    server.web_service = SimpleNamespace(connection_api=SimpleNamespace())
    app = Flask(__name__)
    app.register_blueprint(create_connections_blueprint(server))

    response = app.test_client().post('/api/connections/device-1/kill')

    assert response.status_code == 200
    assert response.json['code'] == 0
    assert sent == ['kill_instance']
