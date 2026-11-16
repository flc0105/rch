"""XT completion only offers targets applicable to the selected Client's current state."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

from core.command_completion.parser import CommandCompletionParser
from server.application.external_tools.external_tool_catalog_service import ExternalToolCatalogService

METAS = Path(__file__).resolve().parents[2] / 'server/resources/external_tools/metas'


class ClientRuntime:
    def __init__(self):
        self.installed = {'gost', 'frp'}
        self.instances = [
            {'tool_id': 'gost.socks5', 'instance_id': 'running-a', 'status': 'running', 'running': True, 'pid': 100},
            {'tool_id': 'gost.socks5', 'instance_id': 'stopped-b', 'status': 'stopped', 'running': False},
            {'tool_id': 'frp.frpc', 'instance_id': 'paused-c', 'status': 'stopping', 'running': False},
            {'tool_id': 'frp.frps', 'instance_id': 'running-d', 'status': 'running', 'running': True, 'pid': 200},
        ]
        self.requests = []
        self.error = False

    def client_install_statuses(self, client_id, packages, **kwargs):
        self.requests.append(('get_install_statuses', client_id, [p['id'] for p in packages]))
        if self.error:
            raise TimeoutError('Client did not reply')
        return {'items': [
            {'installed': p['id'] in self.installed,
             'install_status': 'installed' if p['id'] in self.installed else 'not_installed'}
            for p in packages]}

    def list_all_client_instances(self, client_id, metas):
        self.requests.append(('list_instances', client_id, [m['tool_id'] for m in metas]))
        if self.error:
            raise TimeoutError('Client did not reply')
        allowed = {m['tool_id'] for m in metas}
        return {'items': [row for row in self.instances if row['tool_id'] in allowed]}


def _provider(runtime, *, os_alias='win', arch='amd64'):
    catalog = ExternalToolCatalogService(str(METAS), str(METAS.parent / 'packages'))
    session = SimpleNamespace(session_info=SimpleNamespace(os_alias=os_alias, arch=arch))
    server = SimpleNamespace(get_target_connection_by_client_id=lambda _id: session)
    with patch.dict(sys.modules, {'server.config.config': SimpleNamespace(
            SCRIPT_PATH='', COMMAND_HISTORY_RECENT_LIMIT=30)}):
        from server.application.completion.command_completion_providers import ExternalToolCommandCompletionProvider
    return ExternalToolCommandCompletionProvider(server, catalog, runtime)


def _names(provider, text, client_id='test-client'):
    context = CommandCompletionParser().parse(text, metadata={'client_id': client_id})
    return [item.insert_text for item in provider.complete(context)]


def test_install_and_uninstall_use_client_install_status_and_platform():
    runtime = ClientRuntime()
    provider = _provider(runtime)
    install = _names(provider, 'xt package install ')
    uninstall = _names(provider, 'xt package uninstall ')
    assert 'xt package install gost' not in install
    assert 'xt package install frp' not in install
    assert 'xt package uninstall gost' in uninstall
    assert 'xt package uninstall frp' in uninstall
    assert 'xt package install ffmpeg' in install
    assert 'xt package uninstall ffmpeg' not in uninstall
    assert 'xt package install --package ffmpeg' in _names(provider, 'xt package install --package ')
    assert 'xt package uninstall --package gost' in _names(provider, 'xt package uninstall --package ')
    assert {call[0] for call in runtime.requests} == {'get_install_statuses'}
    assert all(call[1] == 'test-client' for call in runtime.requests)


def test_create_and_start_only_installed_and_start_only_stopped():
    runtime = ClientRuntime()
    provider = _provider(runtime)
    create = _names(provider, 'xt instance create ')
    assert 'xt instance create gost.socks5' in create
    assert 'xt instance create frp.frps' in create
    assert 'xt instance create python-embed.test' not in create
    assert 'xt instance create --module gost.socks5' in _names(provider, 'xt instance create --module ')
    start = _names(provider, 'xt instance start ')
    assert 'xt instance start gost.socks5 stopped-b' in start
    assert 'xt instance start gost.socks5 running-a' not in start
    assert 'xt instance start frp.frpc paused-c' not in start
    assert 'xt instance start frp.frps running-d' not in start
    assert 'xt instance start --module gost.socks5 --name stopped-b' in _names(
        provider, 'xt instance start --module gost.socks5 --name ')
    assert 'xt instance start gost.socks5 stopped-b' in _names(provider, 'xt instance start gost.socks5 ')
    # An installed package disappearing from the Client immediately removes its start target.
    runtime.installed.remove('gost')
    assert 'xt instance start gost.socks5 stopped-b' not in _names(provider, 'xt instance start ')
    assert 'xt instance create gost.socks5' not in _names(provider, 'xt instance create ')


def test_stop_restart_status_logs_have_distinct_lifecycle_filters():
    runtime = ClientRuntime()
    provider = _provider(runtime)
    stop = _names(provider, 'xt instance stop ')
    restart = _names(provider, 'xt instance restart ')
    status = _names(provider, 'xt instance status ')
    logs = _names(provider, 'xt instance logs ')
    assert 'xt instance stop gost.socks5 running-a' in stop
    assert 'xt instance stop frp.frpc paused-c' in stop
    assert 'xt instance stop gost.socks5 stopped-b' not in stop
    assert 'xt instance restart gost.socks5 running-a' in restart
    assert 'xt instance restart frp.frpc paused-c' not in restart
    assert 'xt instance status gost.socks5 stopped-b' in status
    assert 'xt instance logs gost.socks5 stopped-b' in logs
    assert 'xt instance stop --name running-a --module gost.socks5' in _names(provider, 'xt instance stop --name ')
    assert 'xt instance stop --module gost.socks5 --name running-a' in _names(
        provider, 'xt instance stop --module gost.socks5 --name ')
    assert 'xt instance stop frp.frps running-d' in stop
    assert 'xt instance status frp.frps running-d' in status
    assert {call[0] for call in runtime.requests} == {'list_instances'}


def test_exec_short_and_long_syntax_uses_installed_packages_only():
    runtime = ClientRuntime()
    provider = _provider(runtime)
    runtime.installed.add('ffmpeg')
    assert 'xt exec ffmpeg' in _names(provider, 'xt exec ')
    assert 'xt exec python' not in _names(provider, 'xt exec ')
    assert 'xt exec run ffmpeg' in _names(provider, 'xt exec run ')
    assert 'xt exec which ffmpeg' in _names(provider, 'xt exec which ')
    assert 'xt exec info python' in _names(provider, 'xt exec info ')


def test_no_fake_candidates_when_install_state_unavailable():
    runtime = ClientRuntime()
    runtime.error = True
    provider = _provider(runtime)
    assert _names(provider, 'xt package install ') == []
    assert _names(provider, 'xt package uninstall ') == []
    assert _names(provider, 'xt instance create ') == []
    assert _names(provider, 'xt instance start ') == []
    assert _names(provider, 'xt instance stop ') == []
    assert not any(item.startswith('xt exec ffmpeg') for item in _names(provider, 'xt exec '))
    # Static catalog discovery remains available without a Client RPC.
    assert 'xt module list gost' in _names(provider, 'xt module list ')


def test_state_query_is_scoped_to_client_and_no_target_on_unsupported_arch():
    runtime = ClientRuntime()
    provider = _provider(runtime, arch='unavailable_arch')
    # Metadata explicitly using arches=all must remain visible even on unusual targets.
    candidates = _names(provider, 'xt package install ')
    assert 'xt package install java-bundle-demo' in candidates
    assert 'xt package install gost' not in candidates
    assert _names(provider, 'xt instance start ') == []
    assert all('gost.socks5' not in call[2] for call in runtime.requests if call[0] == 'list_instances')


def test_runtime_is_existing_read_only_external_tool_control_path():
    from core.protocol.control import ControlDomain, ExternalToolAction
    from server.application.external_tools.external_tool_runtime_service import ExternalToolRuntimeService

    class Remote:
        def __init__(self):
            self.calls = []

        def run_foreground_control(self, client_id, domain, action, payload, **kwargs):
            self.calls.append((client_id, domain, action, payload, kwargs))
            if action == ExternalToolAction.GET_INSTALL_STATUSES:
                return 1, {'event_type': 'completed', 'status': 'success', 'data': {
                    'items': [{'package_id': row['package_id'], 'installed': row['package_id'] == 'gost'}
                              for row in payload['tools']]}}
            assert action == ExternalToolAction.LIST_INSTANCES
            return 1, {'event_type': 'completed', 'status': 'success', 'data': {
                'items': [{'tool_id': 'gost.socks5', 'instance_id': 'client-one',
                           'status': 'stopped', 'running': False}]}}

    catalog = ExternalToolCatalogService(str(METAS), str(METAS.parent / 'packages'))
    remote = Remote()
    runtime = ExternalToolRuntimeService(catalog, command_execution_api=None, remote_execution_service=remote)
    session = SimpleNamespace(session_info=SimpleNamespace(os_alias='mac', arch='arm64'))
    server = SimpleNamespace(get_target_connection_by_client_id=lambda _id: session)
    with patch.dict(sys.modules, {'server.config.config': SimpleNamespace(
            SCRIPT_PATH='', COMMAND_HISTORY_RECENT_LIMIT=30)}):
        from server.application.completion.command_completion_providers import ExternalToolCommandCompletionProvider
    provider = ExternalToolCommandCompletionProvider(server, catalog, runtime.client_lifecycle_runtime)
    assert 'xt instance create gost.socks5' in _names(provider, 'xt instance create ', client_id='mac-one')
    assert 'xt instance start gost.socks5 client-one' in _names(provider, 'xt instance start ', client_id='mac-one')
    assert 'xt instance stop gost.socks5 client-one' not in _names(provider, 'xt instance stop ', client_id='mac-one')
    assert set(call[2] for call in remote.calls) == {
        ExternalToolAction.GET_INSTALL_STATUSES, ExternalToolAction.LIST_INSTANCES,
    }
    assert all(call[1] == ControlDomain.EXTERNAL_TOOL and call[0] == 'mac-one' for call in remote.calls)
    assert all(call[4].get('source') == 'web_external_tool' for call in remote.calls)
    # The existing client_control_request removes unnecessary package metadata.
    assert all('download_url' not in str(call[3]) for call in remote.calls)
