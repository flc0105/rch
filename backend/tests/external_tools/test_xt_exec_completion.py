"""xt exec nested completion follows the new public command layout."""
from types import SimpleNamespace
from unittest.mock import patch
import sys

from core.command_completion.parser import CommandCompletionParser
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY


class FakeCatalog:
    def list_exec_targets(self, platform_alias, arch):
        assert platform_alias == 'win'
        assert arch == 'amd64'
        return [
            {'exec_name': 'ffmpeg', 'package_id': 'ffmpeg'},
            {'exec_name': 'python', 'package_id': 'python-embed'},
        ]


def test_xt_exec_nested_subcommands_and_exec_names():
    info = SimpleNamespace(os_alias='win', arch='amd64')
    server = SimpleNamespace(get_target_connection_by_client_id=lambda _id: SimpleNamespace(session_info=info))
    # Config imports optional Werkzeug through admin_auth; completion itself needs no auth.
    with patch.dict(sys.modules, {'server.config.config': SimpleNamespace(
        SCRIPT_PATH='', COMMAND_HISTORY_RECENT_LIMIT=30,
    )}):
        from server.application.completion.command_completion_providers import ExternalToolCommandCompletionProvider
    provider = ExternalToolCommandCompletionProvider(server, FakeCatalog())
    parser = CommandCompletionParser()

    def names(text):
        context = parser.parse(text, metadata={'client_id': 'client1'})
        return [item.to_dict()['name'] for item in provider.complete(context)]

    assert names('xt ')[:4] == [
        'xt exec list', 'xt exec info', 'xt exec which', 'xt exec',
    ]
    assert names('xt exec ') == [
        'xt exec list', 'xt exec info', 'xt exec which', 'xt exec',
        'xt exec ffmpeg', 'xt exec python',
    ]
    assert names('xt exec info ') == ['xt exec info ffmpeg', 'xt exec info python']
    assert names('xt exec which p') == ['xt exec which ffmpeg', 'xt exec which python']
    assert names('xt exec f')[-2:] == ['xt exec ffmpeg', 'xt exec python']
    assert names('xt exec ffmpeg -version') == []
    assert names('xt run ') == []
    assert names('xt exec list --json') == []
    assert [item.name for item in SERVER_COMMAND_REGISTRY.get('xt').subcommands] == ['exec', 'package', 'module', 'instance']
