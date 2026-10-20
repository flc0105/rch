"""Unified Client ACMD process operations and selectable cleanup plans."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from client.commands.arguments.registry import ArgumentCommandRegistry
from client.commands.common.commands import CommonCommands
from client.commands.common.mixins.process_ops import CommandProcessMixin
from client.commands.common.services.client_cleanup_service import ClientCleanupService
from client.commands.common.services.process import approved_process_service as aps
from client.commands.common.mixins import update_ops
from client.commands.common.mixins.update_ops import CommandUpdateMixin
from core.protocol.message_types import MSG_TYPE_ACMD
from server.connection.channel.session_command_channel import ClientSessionCommandChannel


def process_row(pid=421):
    return dict(pid=pid, name='demo', user='dev', exec_path='/usr/bin/demo', created_at=1.0,
                cmdline=['demo'], cwd='/tmp', ppid=2, status='running', memory_rss=100,
                threads=1, listening=[])


def executor_owner():
    return SimpleNamespace(_set_timeout=lambda *a, **k: None,
                           _checkpoint=lambda *a, **k: None,
                           _get_process_service=lambda: SimpleNamespace(list_processes=lambda: [
                               {'pid': 421, 'name': 'demo', 'status': 'running', 'username': 'dev'}]))


def test_only_registered_unified_commands():
    assert not hasattr(CommonCommands, 'kill_proc')
    assert not hasattr(CommonCommands, 'kill_port')
    assert not hasattr(CommonCommands, 'pgrep')
    assert not hasattr(CommonCommands, 'pkill')
    assert hasattr(CommonCommands.kill_process, 'help')
    registry = ArgumentCommandRegistry(CommonCommands(socket=None))
    assert registry.has_command('kill') and not registry.has_command('find_proc')
    assert registry.has_command('ps') is False  # ps is platform-specific, remains available there
    templates = registry.get_manifest_payload()
    assert any(x['name'] == 'acmd kill' for x in templates)
    assert not any(x['name'] == 'acmd find_proc' for x in templates)


def test_acmd_interaction_grant_issued_for_kill_only():
    calls = []
    grant_service = SimpleNamespace(issue_script_grant=lambda **kw: (
        calls.append(kw), {'token': 'scoped'})[1])
    channel = ClientSessionCommandChannel(SimpleNamespace(context=SimpleNamespace(
        script_grant_service=grant_service)))
    payload = channel.build_command_payload('acmd kill --pid 421', MSG_TYPE_ACMD,
                                            {'name': 'kill', 'args': {'pid': '421'}})
    assert payload['extra']['__script_grant__']['token'] == 'scoped'
    assert calls[0]['grant_request']['api_grants'] == ['interactions:request']
    payload = channel.build_command_payload('acmd kill --pid 421 --no-confirm', MSG_TYPE_ACMD,
                             {'name': 'kill', 'args': {'pid': '421', 'no-confirm': True}})
    assert '__script_grant__' not in payload.get('extra', {})
    assert '__script_grant__' not in channel.build_command_payload('acmd ps', MSG_TYPE_ACMD,
                                    {'name': 'ps', 'args': {}}).get('extra', {})


def test_kill_no_confirm_never_interacts(monkeypatch):
    monkeypatch.setattr(aps, 'find_targets', lambda criterion: [process_row(421), process_row(422)])
    sent = []
    monkeypatch.setattr(aps, 'terminate_verified', lambda row, **kw: (
        sent.append((row['pid'], kw['force'])), 'SIGKILL' if kw['force'] else 'SIGTERM')[1])
    monkeypatch.setattr(aps.ClientCommandInteractions, '__init__', lambda self, owner:
        pytest.fail('No broker must be created'))
    status, output = CommandProcessMixin._acmd_kill(executor_owner(),
        {'name': 'demo', 'pid': None, 'port': None, 'force': True, 'no-confirm': True})
    assert status == 1 and sent == [(421, True), (422, True)]
    assert output.count('SIGKILL') == 2


def test_kill_preview_can_select_subset_and_force(monkeypatch):
    monkeypatch.setattr(aps, 'find_targets', lambda criteria, **kwargs: [process_row(421),process_row(422)])
    captured = []
    monkeypatch.setattr(aps.ClientCommandInteractions, 'approve_processes',
        lambda self, msg, preview: (captured.append(preview), ({'422'}, False))[1])
    signals = []
    monkeypatch.setattr(aps, 'terminate_verified',lambda row, **kw: (signals.append((row['pid'], kw)), 'SIGTERM')[1])
    status, output = CommandProcessMixin._acmd_kill(executor_owner(),
        {'name': 'demo', 'pid': None, 'port': None, 'force': True, 'no-confirm': False})
    assert status == 1 and signals == [(422, {'force': False, 'port': None})]
    assert captured[0]['switches'][0]['default'] is True
    assert captured[0]['row_ids'] == ['421', '422']


def test_kill_requires_target_without_confirm(monkeypatch):
    monkeypatch.setattr(aps, 'find_targets', lambda *a: pytest.fail('do not enumerate'))
    status, text = CommandProcessMixin._acmd_kill(executor_owner(),
        {'name':'', 'pid':None, 'port':None, 'no-confirm':True})
    assert status == 0 and 'requires' in text


def test_ps_actions_opt_in_and_port_filter(monkeypatch):
    host = executor_owner()
    host._normalize_process_int = lambda value: int(value or 0)
    host._filter_acmd_ps_rows = lambda rows, pid=None, name='': (
        CommandProcessMixin._filter_acmd_ps_rows(host, rows, pid=pid, name=name))
    from client.commands.common.services.process import approved_process_service as service
    monkeypatch.setattr(service, '_port_owners', lambda port: {421} if port == 8080 else set())
    def run(opts):
        return CommandProcessMixin._acmd_ps_common(host, opts)
    status, output = run({'port': 8080, 'json': True})
    assert status == 1 and '_actions' not in output
    status, output = run({'port': 8080, 'json': True, 'with-actions': True})
    assert status == 1
    assert json.loads(output)[0]['_actions'] == [{'label': 'Kill', 'command': 'acmd kill --pid 421'}]
    status, output = run({'port': 8080, 'json': False, 'with-actions': True})
    assert status == 1 and '_actions' not in output


def test_kill_does_not_reject_processes_by_pid_or_current_process(monkeypatch):
    monkeypatch.setattr(aps, 'find_targets', lambda *a, **kw: [process_row(1), process_row(os.getpid())])
    monkeypatch.setattr(aps.ClientCommandInteractions, 'approve_processes',
        lambda self, msg, preview: ({str(1), str(os.getpid())}, False))
    observed = []
    monkeypatch.setattr(aps, 'terminate_verified',
        lambda row, **kw: (observed.append(row['pid']), 'SIGTERM')[1])
    status, output = CommandProcessMixin._acmd_kill(executor_owner(),
        {'name': 'demo', 'pid': None, 'port': None})
    assert status == 1 and observed == [1, os.getpid()]
    assert 'Protected' not in output


def test_generic_planner_does_not_special_case_kill_options():
    from server.application.command.command_planner import CommandPlanner
    from client.commands.arguments.validator import ArgumentCommandValidator
    from client.commands.platform.specs.common import KILL_ARGUMENT_SPEC, PS_ARGUMENT_SPEC
    for command in ('acmd kill --pid 421 --no-confirm -9',
                    'acmd kill --name demo --force --no-confirm',
                    'acmd kill --port 8020 -f --no-confirm'):
        data = CommandPlanner.__new__(CommandPlanner).parse_argument_command(command)
        normalized = ArgumentCommandValidator().normalize(KILL_ARGUMENT_SPEC, data['args'])
        assert normalized['no-confirm'] is True
        assert normalized['force'] or '-9' in normalized.get('_args', [])
    ps = CommandPlanner.__new__(CommandPlanner).parse_argument_command('acmd ps --json --with-actions')
    normalized = ArgumentCommandValidator().normalize(PS_ARGUMENT_SPEC, ps['args'])
    assert normalized['json'] and normalized['with-actions']


def test_cleanup_plan_read_only_and_selected_subset(tmp_path, monkeypatch):
    base = tmp_path / 'downloads'; base.mkdir()
    archive = base / 'rchclient-test.zip'
    # actual archive matcher uses a strict revision filename; mock it for this test only
    archive.write_text('archive')
    unowned = base / 'personal.zip'; unowned.write_text('personal')
    from client.commands.common.services import client_cleanup_service as mod
    monkeypatch.setattr(mod, 'get_client_bundle_download_dir', lambda: str(base))
    monkeypatch.setattr(mod, 'is_bundle_archive', lambda name: name == archive.name)
    service = ClientCleanupService()
    service.ITEMS = ('bundle_archive_residue',)
    plan = service.plan()
    assert archive.exists(), 'preview must not delete files'
    assert plan['items'][0]['paths'][0]['path'] == str(archive)
    result = service.execute_plan(plan, set())
    assert archive.exists() and result['removed_files'] == 0
    result = service.execute_plan(plan, {'bundle_archive_residue'})
    assert not archive.exists() and unowned.exists()
    assert result['removed_files'] == 1


def test_cleanup_changed_snapshot_rejected(tmp_path, monkeypatch):
    base = tmp_path / 'downloads'; base.mkdir()
    f = base/'test-bundle.zip';f.write_text('x')
    from client.commands.common.services import client_cleanup_service as mod
    monkeypatch.setattr(mod, 'get_client_bundle_download_dir', lambda: str(base))
    monkeypatch.setattr(mod, 'is_bundle_archive', lambda name: name == f.name)
    service = ClientCleanupService();service.ITEMS=('bundle_archive_residue',)
    plan = service.plan()
    f.write_text('changed')
    result = service.execute_plan(plan, {'bundle_archive_residue'})
    assert f.exists() and result['removed_files'] == 0
    assert 'changed after preview' in result['items'][0]['skipped_paths'][0]


def test_cleanup_release_current_protected_unbundled_deletes_other_subdirs(tmp_path, monkeypatch):
    root = tmp_path / 'releases';root.mkdir()
    current = root/'live';current.mkdir();(current/'data').write_text('keep')
    stale = root/'obsolete';stale.mkdir();(stale/'user.txt').write_text('old')
    service = ClientCleanupService(current_bundle_resolver=lambda root: str(current))
    service.ITEMS=('bundle_old_releases',)
    from client.commands.common.services import client_cleanup_service as mod
    monkeypatch.setattr(mod, 'get_client_bundle_release_dir', lambda: str(root))
    plan = service.plan()
    assert stale.exists() and current.exists()
    assert plan['items'][0]['paths'][0]['path'] == str(stale)
    service.execute_plan(plan, {'bundle_old_releases'})
    assert current.exists() and (current/'data').exists()
    assert not stale.exists()


def test_clean_command_no_confirm_never_requests_broker(monkeypatch):
    plan = {'items':[{'name':'a','paths':[{'path':'/tmp/fake'}],
         'removed_files':1,'removed_dirs':0,'bytes_freed':1}]}
    monkeypatch.setattr(ClientCleanupService, 'plan', lambda self: plan)
    observed = []
    monkeypatch.setattr(ClientCleanupService, 'execute_plan', lambda self, p, selected:
        (observed.append(selected), {'error_count':0,'items':[],
           'removed_files':0,'removed_dirs':0,'bytes_freed':0})[1])
    host = SimpleNamespace(_set_timeout=lambda *_: None, _checkpoint=lambda **_:None,
                           _get_current_bundle_release_dir=lambda _: '',
                           _format_client_cleanup_result=lambda result:'ok')
    monkeypatch.setattr(update_ops.CommandUpdateMixin, '_format_client_cleanup_result',
                        lambda self,result:'ok')
    monkeypatch.setattr('client.commands.common.services.interaction_service.CommandInteractions',
                        lambda owner: pytest.fail('no broker'))
    status, output=CommandUpdateMixin.clean(host, '--no-confirm')
    assert status == 1 and observed == [{'a'}], (status, output)


def test_cleanup_rejects_new_nested_file_after_preview(tmp_path, monkeypatch):
    from client.commands.common.services import client_cleanup_service as mod
    root = tmp_path / 'releases'; root.mkdir()
    old = root / 'stale'; old.mkdir()
    nested = old / 'sub'; nested.mkdir()
    (nested / 'original.txt').write_text('old')
    monkeypatch.setattr(mod, 'get_client_bundle_release_dir', lambda: str(root))
    service = ClientCleanupService(current_bundle_resolver=lambda path: '')
    service.ITEMS = ('bundle_old_releases',)
    plan = service.plan()
    assert old.exists(), 'Preview must be read-only'
    (nested / 'unexpected.txt').write_text('changed after approval')
    result = service.execute_plan(plan, {'bundle_old_releases'})
    assert old.exists() and (nested / 'unexpected.txt').exists()
    assert any('changed after preview' in msg for msg in result['items'][0]['skipped_paths'])


def test_no_confirm_mass_match_not_limited_by_preview_ui(monkeypatch):
    seen = []
    monkeypatch.setattr(aps, 'find_targets', lambda criteria, **kwargs: (seen.append(kwargs), [process_row(421)])[1])
    monkeypatch.setattr(aps, 'terminate_verified', lambda row, **kwargs: 'SIGTERM')
    status, _ = CommandProcessMixin._acmd_kill(executor_owner(),
                    {'name': 'demo', 'pid': None, 'port': None, 'force': False, 'no-confirm': True})
    assert status == 1 and seen == [{}]


def test_server_cli_kill_boolean_switches_do_not_swallow_force_alias():
    from server.application.command.command_planner import CommandPlanner
    from client.commands.arguments.validator import ArgumentCommandValidator
    from client.commands.platform.specs.common import KILL_ARGUMENT_SPEC
    for command in ('acmd kill --pid 421 --no-confirm -9',
                    'acmd kill --name demo --force --no-confirm',
                    'acmd kill --port 8020 -f --no-confirm'):
        parsed = CommandPlanner.__new__(CommandPlanner).parse_argument_command(command)
        normalized = ArgumentCommandValidator().normalize(KILL_ARGUMENT_SPEC, parsed['args'])
        assert normalized['no-confirm'] is True
        assert normalized['force'] or any(item == '-9' for item in normalized.get('_args', []))
