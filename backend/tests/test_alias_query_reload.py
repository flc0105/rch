import json
import os
import tempfile
import unittest

from server.application.command.alias_manager import AliasManager
from server.application.command.builtin_command_support import AliasBuiltinSupport
from server.application.web.quick_action_api import WebQuickActionApi


class _SessionInfo:
    os_type = 'Darwin'
    os_alias = 'mac'


class _Connection:
    session_info = _SessionInfo()


class _Server:
    def __init__(self, session):
        self.session = session

    def get_target_connection_by_client_id(self, client_id):
        if client_id != 'client-1':
            raise KeyError(client_id)
        return self.session


class AliasQueryReloadTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.alias_path = os.path.join(self.temp_dir.name, 'aliases.json')
        self._write_aliases({
            'common': {'before': 'getinfo'},
            'mac': {'mac_before': 'pwd'},
        })

        self.manager = AliasManager.__new__(AliasManager)
        self.manager.alias_path = self.alias_path
        self.manager.aliases = self.manager._create_empty_aliases()
        self.manager.load_aliases()
        self.conn = _Connection()
        self.support = AliasBuiltinSupport(self.manager, self.conn)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_aliases(self, payload):
        with open(self.alias_path, 'w', encoding='utf-8') as file_obj:
            json.dump(payload, file_obj, ensure_ascii=False, indent=2)

    def test_alias_list_reloads_direct_json_edits(self):
        self._write_aliases({
            'common': {'after': 'getinfo'},
            'mac': {'mac_after': 'pwd'},
        })

        result = list(self.support.alias('list --json'))
        payload = json.loads(result[0][1])
        names = {(item['platform'], item['alias']) for item in payload}

        self.assertIn(('common', 'after'), names)
        self.assertIn(('mac', 'mac_after'), names)
        self.assertNotIn(('common', 'before'), names)
        self.assertNotIn(('mac', 'mac_before'), names)

    def test_alias_resolve_reloads_direct_json_edits(self):
        self._write_aliases({
            'common': {'common_after': 'getinfo'},
            'mac': {'effective_after': 'pwd'},
        })

        result = list(self.support.alias('--json'))
        payload = json.loads(result[0][1])
        names = {item['alias'] for item in payload}

        self.assertEqual({'common_after', 'effective_after'}, names)

    def test_quick_actions_list_already_reloads_direct_json_edits(self):
        api = WebQuickActionApi(
            server=_Server(self.conn),
            alias_manager=self.manager,
            command_execution_api=None,
        )
        self._write_aliases({
            'common': {'qa_after': 'getinfo'},
            'mac': {'qa_mac_after': 'pwd'},
        })

        payload = api.list_quick_actions('client-1')
        names = {(item['platform'], item['alias']) for item in payload['items']}

        self.assertIn(('common', 'qa_after'), names)
        self.assertIn(('mac', 'qa_mac_after'), names)
        self.assertNotIn(('common', 'before'), names)
        self.assertNotIn(('mac', 'mac_before'), names)


if __name__ == '__main__':
    unittest.main()
