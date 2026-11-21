"""Connect/disconnect surface of the existing Web connection facade."""
from types import SimpleNamespace

from server.application.web.connection_api import WebConnectionApi


class Connector:
    def __init__(self):
        self.calls = []

    def connect(self, host, port):
        self.calls.append(('connect', host, port))
        return SimpleNamespace(session_info=SimpleNamespace(client_id='client-001'))

    def disconnect(self, client_id):
        self.calls.append(('disconnect', client_id))
        return client_id


def test_bind_web_api_delegates_to_connection_domain():
    connector = Connector()
    api = WebConnectionApi(connection_service=object(), bind_connector=connector)
    assert api.connect_bind_client('192.168.1.25', 9443) == {'client_id': 'client-001'}
    assert api.disconnect_bind_client('client-001') == {'client_id': 'client-001'}
    assert connector.calls == [('connect', '192.168.1.25', 9443), ('disconnect', 'client-001')]
