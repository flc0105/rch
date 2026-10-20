"""v34.6: CLI catalog visibility, fast-result routing and download validation."""
from pathlib import Path
from types import SimpleNamespace
import json

from core.platform.catalog_visibility import visible_on_platform
from core.utils.script_metadata import read_script_metadata_from_file
from server.application.command.builtin_command_support import ScriptBuiltinSupport
from server.application.command.job_builtin_support import JobBuiltinSupport
from server.application.completion.command_completion_providers import (
    ScriptCommandCompletionProvider, JobCommandCompletionProvider,
)
from core.command_completion.models import CompletionContext
from client.commands.common.mixins.file_cli_ops import CommandFileCliMixin
from client.commands.common.services.filesystem.path_resolver import PathResolver
from server.connection.channel.session_command_channel import ClientSessionCommandChannel
from server.connection.runtime.session_runtime import ClientSessionRuntime
from server.connection.services.result_dispatcher import ServerResultDispatcher


def test_platform_metadata_precedes_directory_and_exec_stays_unrestricted(tmp_path, monkeypatch):
    import server.application.command.builtin_command_support as builtin_module
    monkeypatch.setattr(builtin_module, 'SCRIPT_PATH', str(tmp_path))
    def script(name, platforms):
        file = tmp_path / name
        file.parent.mkdir(exist_ok=True, parents=True)
        file.write_text(f'SCRIPT_METADATA = {{"platforms": {platforms!r}}}\nprint("ok")\n')
        return file
    script('common/all.py', ['all'])
    script('mac/right.py', ['mac'])
    script('mac/wrong.py', ['linux'])
    script('linux/left.py', ['linux'])
    script('linux/override.py', ['mac'])
    script('common/rejected.py', ['win'])
    plans=[]
    plan_builder=SimpleNamespace(build_script_plan=lambda text,extra: plans.append((text,extra)) or {'command_type':'script'})
    support=ScriptBuiltinSupport(plan_builder, lambda: lambda plan: lambda: iter([(1,'executed')]),
                                 conn=SimpleNamespace(session_info=SimpleNamespace(os_alias='Darwin')))
    names=set(support.list_scripts())
    assert names == {'common/all.py','mac/right.py','linux/override.py'}
    json_rows=json.loads(list(support.script('list','--json'))[0][1])
    assert {row['name'] for row in json_rows} == names
    assert list(support.script('exec','linux/left.py')) == [(1,'executed')]
    assert plans, 'Explicit execution remains possible across platform boundaries'
    fake_server=SimpleNamespace(get_target_connection_by_client_id=lambda _: SimpleNamespace(
        session_info=SimpleNamespace(os_alias='mac')))
    provider=ScriptCommandCompletionProvider(fake_server,script_root=str(tmp_path))
    matches={item.metadata['script'] for item in provider.complete(CompletionContext(
        command_name='script',argument_text='exec ',metadata={'client_id':'c1'}))}
    assert matches == names


def test_job_cli_and_completion_only_filter_user_facing_catalog():
    items=[
        {'job_name':'common/a','metadata':{'platforms':['all']}},
        {'job_name':'linux/a','metadata':{'platforms':['linux']}},
        {'job_name':'mac/a','metadata':{'platforms':['mac']}},
        {'job_name':'linux/b','metadata':{'platforms':['mac']}},
    ]
    api=SimpleNamespace(list_background_job_catalog=lambda _client: items)
    server=SimpleNamespace(web_service=SimpleNamespace(job_api=api),
        get_target_connection_by_client_id=lambda _:SimpleNamespace(session_info=SimpleNamespace(os_alias='mac')))
    conn=SimpleNamespace(session_info=SimpleNamespace(client_id='c1', os_alias='mac'))
    cli=JobBuiltinSupport(server,conn,None)
    output=list(cli.execute_subcommand('list',''))
    assert output == [(1,'common/a\nmac/a\nlinux/b')]
    assert [e['name'] for e in json.loads(list(cli.execute_subcommand('list','--json'))[0][1])] == [
        'common/a','mac/a','linux/b']
    provider=JobCommandCompletionProvider(server)
    names={c.name for c in provider.complete(CompletionContext(command_name='job',argument_text='start ',metadata={'client_id':'c1'}))}
    assert names == {'common/a','mac/a','linux/b'}
    assert len(api.list_background_job_catalog('c1'))==4, 'Web UI catalog remains unfiltered'


def test_download_without_filename_fails_before_path_or_transfer(tmp_path):
    obj=CommandFileCliMixin()
    obj.path_resolver=PathResolver()
    obj._set_cancel_policy=lambda **kwargs: None
    assert obj.download('') == (0, 'Usage: download <file>')
    assert 'Not a file:' in obj.download(str(tmp_path))[1]


def test_fast_client_result_is_expected_not_background():
    unexpected=[]
    class Session:
        def __init__(self):
            self.runtime=ClientSessionRuntime()
            self.context=SimpleNamespace(on_unexpected_message=lambda *args:unexpected.append(args),
                                         command_history_orchestrator=None,script_grant_service=None)
            self.session_info=SimpleNamespace(client_id='c1')
        def send(self,data):
            ServerResultDispatcher(self).dispatch_result(data['id'],0,'Usage: download <file>',1)
    session=Session()
    channel=ClientSessionCommandChannel(session)
    assert list(channel.send_command('download')) == [(0,'Usage: download <file>')]
    assert unexpected==[]
    assert session.runtime.pending_command_ids.empty()
