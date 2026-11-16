"""xt exec nested completion follows the new public command layout."""
from types import SimpleNamespace
from unittest.mock import patch
import sys

from core.command_completion.parser import CommandCompletionParser
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY


class FakeCatalog:
    def list_packages(self):
        return [{'id': 'ffmpeg'}, {'id': 'python-embed'}]

    def _platform_matches(self, package, platform):
        return platform == 'win'

    def _arch_matches(self, package, arch):
        return arch == 'amd64'

    def list_exec_targets(self, platform_alias, arch):
        assert platform_alias == 'win'
        assert arch == 'amd64'
        return [
            {'exec_name': 'ffmpeg', 'package_id': 'ffmpeg'},
            {'exec_name': 'python', 'package_id': 'python-embed'},
        ]


class FakeClientRuntime:
    def client_install_statuses(self, _client_id, packages, **_kwargs):
        return {'items': [{'installed': p['id'] == 'ffmpeg'} for p in packages]}


def test_xt_exec_nested_subcommands_and_exec_names():
    info = SimpleNamespace(os_alias='win', arch='amd64')
    server = SimpleNamespace(get_target_connection_by_client_id=lambda _id: SimpleNamespace(session_info=info))
    # Config imports optional Werkzeug through admin_auth; completion itself needs no auth.
    with patch.dict(sys.modules, {'server.config.config': SimpleNamespace(
        SCRIPT_PATH='', COMMAND_HISTORY_RECENT_LIMIT=30,
    )}):
        from server.application.completion.command_completion_providers import ExternalToolCommandCompletionProvider
    provider = ExternalToolCommandCompletionProvider(server, FakeCatalog(), FakeClientRuntime())
    parser = CommandCompletionParser()

    def names(text):
        context = parser.parse(text, metadata={'client_id': 'client1'})
        return [item.to_dict()['name'] for item in provider.complete(context)]

    # XT itself supplies only runtime targets; static paths belong to the Registry.
    assert names('xt ') == []
    assert names('xt instance cre') == []
    static = [name for name, _ in SERVER_COMMAND_REGISTRY.completion_paths('xt')]
    assert 'xt instance create ' in static
    assert 'xt exec info ' in static
    assert 'xt exec run ' in static
    assert names('xt exec ') == ['xt exec ffmpeg']
    assert names('xt exec info ') == ['xt exec info ffmpeg', 'xt exec info python']
    assert names('xt exec which p') == ['xt exec which ffmpeg']
    assert names('xt exec f')[-1:] == ['xt exec ffmpeg']
    assert names('xt exec run ') == ['xt exec run ffmpeg']
    assert names('xt exec ffmpeg -version') == []
    assert names('xt run ') == []
    assert names('xt exec list --json') == []
    assert [item.name for item in SERVER_COMMAND_REGISTRY.get('xt').subcommands] == ['exec', 'package', 'module', 'instance', 'help']
