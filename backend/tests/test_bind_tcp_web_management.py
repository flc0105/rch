"""Connect and saved Bind target state through the existing Web facade."""
from types import SimpleNamespace

from server.application.connection.saved_bind_target_store import SavedBindTargetStore
from server.application.web.connection_api import WebConnectionApi
from server.persistence.rch_database import RchDatabase


class Connector:
    def __init__(self):
        self.calls = []
        self.session = SimpleNamespace(session_info=SimpleNamespace(
            client_id='client-001', machine_id='same-machine', hostname='host',
            os_type='macOS', os_ver='13', integrity='User',
        ))

    def connect_with_status(self, host, port, *, server_web_base_url=''):
        self.calls.append(('connect', host, port, server_web_base_url))
        return self.session, len(self.calls) > 1

    def disconnect(self, client_id):
        self.calls.append(('disconnect', client_id))
        return client_id


def test_bind_web_api_delegates_and_persists_target_without_duplicates(tmp_path):
    connector = Connector()
    database = RchDatabase(str(tmp_path / 'rch.db'))
    api = WebConnectionApi(connection_service=object(), bind_connector=connector,
                           saved_bind_target_store=SavedBindTargetStore(database))
    try:
        first = api.connect_bind_client('192.168.1.25', 9443, 'http://server.test:8085')
        second = api.connect_bind_client('192.168.1.25', 9443, 'http://server.test:8085')
        assert first['client_id'] == second['client_id'] == 'client-001'
        assert first['status'] == 'connected'
        assert second['status'] == 'already_connected'
        assert first['target_id'] == second['target_id']
        assert len(api.list_saved_bind_targets()) == 1
        assert api.list_saved_bind_targets()[0]['machine_id'] == 'same-machine'
        assert connector.calls == [
            ('connect', '192.168.1.25', 9443, 'http://server.test:8085'),
            ('connect', '192.168.1.25', 9443, 'http://server.test:8085'),
        ]
    finally:
        database.close_thread_connection()
