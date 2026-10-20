"""v34.8: only explicit metadata.platforms controls terminal discovery."""
import json
from types import SimpleNamespace

from core.platform.catalog_visibility import visible_on_platform
from server.application.command.builtin_command_support import ScriptBuiltinSupport
from server.application.command.job_builtin_support import JobBuiltinSupport
from server.application.completion.command_completion_providers import (
    ScriptCommandCompletionProvider, JobCommandCompletionProvider,
)
from core.command_completion.models import CompletionContext


def test_visible_on_platform_ignores_paths_and_requires_schema():
    assert not visible_on_platform({'path':'common/test.py','metadata':{}}, 'mac')
    assert not visible_on_platform({'path':'mac/test.py','metadata':{'platforms':[]}}, 'mac')
    assert not visible_on_platform({'job_name':'mac/test','metadata':{'platforms':['linux']}}, 'mac')
    assert visible_on_platform({'path':'linux/test.py','metadata':{'platforms':['mac']}}, 'Darwin')
    assert visible_on_platform({'path':'misc/test.py','metadata':{'platforms':['common']}}, 'mac')
    assert visible_on_platform({'path':'any/test.py','metadata':{'platforms':['all']}}, 'win')


def test_script_list_and_completion_schema_only_without_blocking_execution(tmp_path, monkeypatch):
    import server.application.command.builtin_command_support as script_module
    monkeypatch.setattr(script_module,'SCRIPT_PATH', str(tmp_path))
    for path, declaration in {
        'common/undefined.py': '',
        'mac/undefined.py': 'SCRIPT_METADATA = {}\n',
        'mac/declared.py': "SCRIPT_METADATA = {'platforms': ['mac']}\n",
        'linux/override.py': "SCRIPT_METADATA = {'platforms': ['mac']}\n",
        'common/unsupported.py': "SCRIPT_METADATA = {'platforms': ['win']}\n",
        'misc/all.py': "SCRIPT_METADATA = {'platforms': ['common']}\n",
    }.items():
        p=tmp_path/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(declaration+'print(1)\n')
    executed=[]
    builder=SimpleNamespace(build_script_plan=lambda text,extra: executed.append(text) or {'command_type':'script'})
    support=ScriptBuiltinSupport(builder,lambda:lambda plan:lambda:iter([(1,'ok')]),
                                conn=SimpleNamespace(session_info=SimpleNamespace(os_alias='Darwin')))
    expected={'mac/declared.py','linux/override.py','misc/all.py'}
    assert set(support.list_scripts())==expected
    result=list(support.script('list','--json'))
    assert {row['name'] for row in json.loads(result[0][1])}==expected
    server=SimpleNamespace(get_target_connection_by_client_id=lambda _:
                          SimpleNamespace(session_info=SimpleNamespace(os_alias='mac')))
    provider=ScriptCommandCompletionProvider(server,script_root=str(tmp_path))
    suggestions=provider.complete(CompletionContext(command_name='script', argument_text='exec ',metadata={'client_id':'c1'}))
    assert {row.metadata['script'] for row in suggestions}==expected
    assert list(support.script('exec','mac/undefined.py'))==[(1,'ok')]
    assert executed, 'Explicit execution is not gated by catalog visibility'


def test_job_list_and_completion_schema_only_without_touching_web_catalog():
    items=[
        {'job_name':'common/undefined','metadata':{}},
        {'job_name':'mac/undefined','metadata':{'platforms':[]}},
        {'job_name':'linux/override','metadata':{'platforms':['mac']}},
        {'job_name':'common/declared','metadata':{'platforms':['common']}},
        {'job_name':'mac/windows','metadata':{'platforms':['win']}},
    ]
    api=SimpleNamespace(list_background_job_catalog=lambda _client:items)
    server=SimpleNamespace(web_service=SimpleNamespace(job_api=api),
        get_target_connection_by_client_id=lambda _:SimpleNamespace(session_info=SimpleNamespace(os_alias='mac')))
    cli=JobBuiltinSupport(server,SimpleNamespace(session_info=SimpleNamespace(client_id='c1',os_alias='mac')),None)
    expected={'linux/override','common/declared'}
    names=set(list(cli.execute_subcommand('list',''))[0][1].splitlines())
    assert names==expected
    assert {row['name'] for row in json.loads(list(cli.execute_subcommand('list','--json'))[0][1])}==expected
    provider=JobCommandCompletionProvider(server)
    suggestions=provider.complete(CompletionContext(command_name='job',argument_text='start ',metadata={'client_id':'c1'}))
    assert {row.name for row in suggestions}==expected
    assert len(api.list_background_job_catalog('c1'))==len(items)
