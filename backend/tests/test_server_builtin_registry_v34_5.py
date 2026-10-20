"""v34.5: a single Server command catalog controls dispatch, help and suggestions."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.command_completion.models import CompletionContext
from core.protocol.structured_arg_codec import encode_structured_arg
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY as registry
from server.application.command.builtin_command_handler import BuiltinCommandHandler
from server.application.command.builtin_command_support import ScriptBuiltinSupport, AliasBuiltinSupport
from server.application.command.job_builtin_support import JobBuiltinSupport
from server.application.completion.command_completion_providers import (
    RegisteredServerSubcommandCompletionProvider, JobCommandCompletionProvider,
)
from server.application.history.quick_history import QuickHistoryRecordPolicy


def test_registry_is_only_builtin_allowlist_and_manifest_source():
    names = {item['name'] for item in registry.candidates()}
    assert {'alias', 'job', 'script', 'xt', 'history', 'notify', 'saveout', 'help'} <= names
    assert {'exec', 'run_script', 'resolve', 'reload', 'get_command_candidates'} & names == set()
    assert registry.parse('not_a_builtin', 'anything') is None
    assert BuiltinCommandHandler.__dict__.get('WEB_COMMAND_TEMPLATES') is None
    assert registry.parse('script', '')[1:] == ('list', '')
    assert registry.parse('script', 'exec mac/a.py --name "hello world"')[1:] == (
        'exec', 'mac/a.py --name "hello world"')
    assert registry.parse('script', 'run __json__:eyJ9')[1:] == ('run', '__json__:eyJ9')
    assert registry.parse('xt', 'tool-a -- -v')[1:] == ('__direct__', 'tool-a -- -v')
    assert registry.parse('alias', '--json')[1:] == ('list', '--json')
    assert registry.parse('history', 'run 12')[1:] == ('run', '12')
    with pytest.raises(ValueError):
        registry.parse('alias', 'reload')
    with pytest.raises(ValueError):
        registry.parse('script', 'which foo')
    assert 'script run' in registry.help('script')
    assert 'script exec' in registry.help('script exec')


def test_script_end_to_end_server_plan_and_safe_view(tmp_path, monkeypatch):
    import server.application.command.builtin_command_support as module
    monkeypatch.setattr(module, 'SCRIPT_PATH', str(tmp_path))
    file = tmp_path / 'common' / 'demo.py'
    file.parent.mkdir()
    file.write_text("SCRIPT_METADATA = {'platforms': ['common']}\n# test script\nprint(123)\n", encoding='utf-8')
    plans = []
    planner = SimpleNamespace(build_script_plan=lambda text, extra: plans.append((text,extra)) or
                              {'command': text, 'command_type':'script', 'extra': extra})
    support = ScriptBuiltinSupport(plan_builder=planner,
                    plan_executor_factory=lambda: lambda plan: lambda: iter([(1, 'executed')]))
    assert list(support.script('list')) == [(1, 'common/demo.py')]
    entries = json.loads(list(support.script('list', '--json'))[0][1])
    assert entries[0]['name'] == 'common/demo.py'
    assert set(entries[0]) == {'name','display_name','description','params'}
    assert 'print(123)' in list(support.script('view', 'common/demo.py'))[0][1]
    assert list(support.script('exec', 'common/demo.py')) == [(1, 'executed')]
    assert plans[-1][0] == file.read_text()
    assert list(support.script('run',encode_structured_arg({'script_name':'common/demo', 'params':{'x':'y'}}))) == [(1, 'executed')]
    assert plans[-1][1]['__script_name__'] == 'common/demo'
    assert plans[-1][1]['x'] == 'y'
    with pytest.raises(ValueError):
        list(support.script('view', '../../other.py'))
    outside = tmp_path.parent / 'inaccessible.py'
    (tmp_path / 'common' / 'link.py').symlink_to(outside)
    with pytest.raises(ValueError):
        list(support.script('view', 'common/link.py'))


def test_completions_share_registry_and_job_catalog():
    p = RegisteredServerSubcommandCompletionProvider()
    context = CompletionContext(raw_input='script ', command_name='script',argument_text='')
    names = {c.title for c in p.complete(context)}
    assert names == {'script list', 'script view', 'script exec', 'script run'}
    context = CompletionContext(raw_input='alias ', command_name='alias',argument_text='')
    assert {c.title for c in p.complete(context)} == {'alias list','alias set','alias unset'}
    context = CompletionContext(raw_input='job ', command_name='job', argument_text='')
    assert {c.title for c in p.complete(context)} == {'job list','job start','job ps','job status','job stop','job stop-all'}
    server = SimpleNamespace(web_service=SimpleNamespace(job_api=SimpleNamespace(
        list_background_job_catalog=lambda client: [{'job_name':'common/hello', 'metadata': {'platforms': ['common']}}]
    )))
    dynamic = JobCommandCompletionProvider(server)
    context = CompletionContext(raw_input='job start ', command_name='job',argument_text='start ',
                                metadata={'client_id':'c1'})
    assert dynamic.complete(context)[0].insert_text == 'job start common/hello'


def test_quick_keeps_manually_typed_script_run_but_not_history_replay():
    assert QuickHistoryRecordPolicy.should_record('script run __json__:abc', source='web')
    assert not QuickHistoryRecordPolicy.should_record('script run __json__:abc', source='web',metadata={'script_run':True})
    assert not QuickHistoryRecordPolicy.should_record('history run 3',source='cli')
    assert not QuickHistoryRecordPolicy.should_record('!3',source='cli')


def test_builtin_script_dispatch_never_claims_obsolete_commands():
    handler = BuiltinCommandHandler.__new__(BuiltinCommandHandler)
    support = Mock()
    support.script.return_value = iter([(1,'OK')])
    handler.script_support = support
    assert handler.resolve_builtin_command('run_script', '__json__:abc') is None
    assert handler.resolve_builtin_command('exec', 'anything.py') is None
    assert list(handler.resolve_builtin_command('script', 'exec common/foo.py')) == [(1, 'OK')]
    support.script.assert_called_once_with('exec', 'common/foo.py')
