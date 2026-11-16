"""Per-run Script modes, live configuration, output and lifecycle contracts."""
import io
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from client.config import runtime_config
from client.controls.dispatcher import ClientControlDispatcher
from client.controls.registration import register_control_domain
from core.protocol.control import ControlDomain, ScriptAction
from client.runtime.execution.runtime import ExecutionRuntime
from client.scripts.manager import ScriptManager
from core.protocol.script_execution import (
    EXECUTION_CONFIG, OUTPUT_CONFIG, normalize_execution_schema, run_mode_options,
    resolve_run_modes,
)
from server.application.scripts.script_run_service import prepare_script_control


def config(execution='inproc', output='collect', go=False):
    return {'items': [
        {'key': EXECUTION_CONFIG, 'value': execution, 'choices': ['subprocess_pipe'] if go else ['inproc','subprocess_pipe']},
        {'key': OUTPUT_CONFIG, 'value': output, 'choices': ['collect','stream']},
    ]}


def test_schema_priority_and_live_config(tmp_path):
    script = tmp_path / 'probe.py'
    script.write_text('print(1)')
    assert prepare_script_control(str(tmp_path),'probe',{},config=config())['execution_mode'] == 'inproc'
    request = prepare_script_control(str(tmp_path),'probe',{},config=config('subprocess_pipe','stream'))
    assert (request['execution_mode'], request['output_mode']) == ('subprocess_pipe','stream')
    script.write_text('SCRIPT_METADATA = '+repr({'execution':{'modes':{'allowed':['inproc','subprocess_pipe'],'default':'inproc'},'output':{'allowed':['collect','stream'],'default':'collect'}}})+'\nprint(1)')
    request = prepare_script_control(str(tmp_path),'probe',{},config=config('subprocess_pipe','stream'))
    assert (request['execution_mode'], request['output_mode']) == ('inproc','collect')
    request = prepare_script_control(str(tmp_path),'probe',{},config=config(),execution_mode='subprocess_pipe',output_mode='stream')
    assert (request['execution_mode'],request['output_mode']) == ('subprocess_pipe','stream')
    assert 'execution_mode' not in request['params']
    options = run_mode_options({'execution': {'modes':{'default':'inproc'}}},config('subprocess_pipe',go=True)['items'])
    assert options['execution_mode'] == {'allowed':['subprocess_pipe'],'default':None}
    with pytest.raises(ValueError): resolve_run_modes(options)
    assert resolve_run_modes(options,execution_mode='subprocess_pipe').execution_mode.value == 'subprocess_pipe'
    restricted = run_mode_options({'execution': {'output':{'allowed':['collect'],'default':'collect'}}},config()['items'])
    with pytest.raises(ValueError,match='output_mode'): resolve_run_modes(restricted,output_mode='stream')


@pytest.mark.parametrize('schema',[{'modes':{'allowed':[]}}, {'modes':{'default':'bad'}}, {'output':{'allowed':['stream'],'default':'collect'}}, {'output':{'allowed':['stream','stream']}}, {'unknown':{}}])
def test_invalid_schema_rejected(schema):
    with pytest.raises(ValueError): normalize_execution_schema(schema)


def harness():
    frames = []
    sock = SimpleNamespace(client_id='mode-test', client_session_token='', send_result=lambda *args: frames.append(args),
                           send_event=lambda request_id, event: frames.append(event))
    execution = ExecutionRuntime(sock)
    manager = ScriptManager()
    dispatcher = ClientControlDispatcher(execution)
    register_control_domain(dispatcher, ControlDomain.SCRIPT, manager.execute, cancel_policies={ScriptAction.RUN: manager.cancel_policy})
    return dispatcher, execution, frames


def payload(code, execution, output):
    return {'script_name':'test/probe','source':code,'params':{},'execution_mode':execution,'output_mode':output}


@pytest.mark.parametrize('mode',['inproc','subprocess_pipe'])
@pytest.mark.parametrize('output',['collect','stream'])
def test_four_modes_actual_python(mode,output):
    dispatch, runtime, frames = harness()
    source = 'import os, sys\nprint(os.getpid())\nprint("中文")\nprint()\nprint("warning",file=sys.stderr)\nprint("tail",end="")'
    status, result = dispatch.execute(1,'script','run',payload(source,mode,output))
    assert status == 1
    if output == 'collect':
        assert not frames
        lines = result.splitlines()
    else:
        assert result == 'Code execution completed'
        assert all(frame['event_type']=='chunk' for frame in frames)
        lines = [frame['message'] for frame in frames]
    assert (int(lines[0]) == os.getpid()) == (mode=='inproc')
    assert lines[1:] == ['中文','','warning','tail']
    assert runtime.context_store.get_existing(1) is None


@pytest.mark.parametrize('mode',['inproc','subprocess_pipe'])
@pytest.mark.parametrize('output',['collect','stream'])
def test_real_time_vs_collect(mode,output):
    dispatch, runtime, frames = harness()
    result=[]
    worker=threading.Thread(target=lambda:result.append(dispatch.execute(1,'script','run',payload('import time\nprint("first",flush=True)\ntime.sleep(0.8)\nprint("last")',mode,output))))
    worker.start()
    deadline=time.monotonic()+4
    if output=='stream':
        while not frames and worker.is_alive() and time.monotonic()<deadline: time.sleep(.01)
        assert frames and frames[0]['message']=='first' and worker.is_alive()
    else:
        time.sleep(.2)
        assert not frames and worker.is_alive()
    worker.join(5)
    assert not worker.is_alive() and result[0][0]==1
    assert ('last' in result[0][1]) if output=='collect' else any(f['message']=='last' for f in frames)


@pytest.mark.parametrize('output',['collect','stream'])
def test_subprocess_timeout_preserves_output(monkeypatch,output):
    monkeypatch.setattr(runtime_config,'SCRIPT_DEFAULT_TIMEOUT',3)
    dispatch,runtime,frames=harness()
    started=time.monotonic()
    status, result=dispatch.execute(1,'script','run',payload('import time\nprint("before",flush=True)\ntime.sleep(30)','subprocess_pipe',output))
    assert time.monotonic()-started<8
    assert status==0 and result['failure_reason']=='timed_out'
    assert 'before' in result['text'] if output=='collect' else any(f['message']=='before' for f in frames)
    assert runtime.context_store.get_existing(1) is None


@pytest.mark.parametrize('output',['collect','stream'])
def test_subprocess_cancel_preserves_output(output,tmp_path):
    dispatch,runtime,frames=harness()
    ready=tmp_path/'ready'
    request=payload(f'import time\nfrom pathlib import Path\nprint("before",flush=True)\nPath({str(ready)!r}).touch()\ntime.sleep(30)','subprocess_pipe',output)
    result=[]
    dispatch.prepare(1,'script','run',request)
    worker=threading.Thread(target=lambda:result.append(dispatch.execute(1,'script','run',request)))
    worker.start()
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        context=runtime.context_store.get_existing(1)
        if context and context._cancel_handlers: break
        time.sleep(.01)
    else: pytest.fail('no process registered')
    while not ready.exists() and time.monotonic()<deadline: time.sleep(.01)
    assert ready.exists(), 'child must produce output before cancellation'
    if output=='stream':
        while not frames and time.monotonic()<deadline: time.sleep(.01)
    assert runtime.cancel(1)['accepted']
    worker.join(5)
    assert not worker.is_alive()
    status,data=result[0]
    assert status==0 and data['event_type']=='cancelled'
    assert 'before' in data['text'] if output=='collect' else any(f['message']=='before' for f in frames)
    assert runtime.context_store.get_existing(1) is None


def test_cancel_before_dispatch_and_reject_inproc(monkeypatch):
    dispatch,runtime,frames=harness()
    request=payload('raise RuntimeError("should not run")','subprocess_pipe','collect')
    dispatch.prepare(1,'script','run',request)
    assert runtime.cancel(1)['accepted']
    status,data=dispatch.execute(1,'script','run',request)
    assert status==0 and data['event_type']=='cancelled' and runtime.context_store.get_existing(1) is None
    request=payload('print("ok")','inproc','collect')
    dispatch.prepare(2,'script','run',request)
    assert not runtime.cancel(2)['accepted']
    assert dispatch.execute(2,'script','run',request)==(1,'ok\n')
    assert dispatch.execute(3,'script','run',{**request,'execution_mode':'bad'})[0]==0
    assert dispatch.execute(4,'script','run',{**request,'source':"SCRIPT_METADATA={'execution':{'modes':{'allowed':['subprocess_pipe']}}}\nprint(1)"})[0]==0


def test_inproc_output_is_thread_local(monkeypatch):
    from client.runtime.execution.python_execution.output import capture_output
    original=io.StringIO()
    monkeypatch.setattr(sys,'stdout',original)
    sink=io.StringIO()
    with capture_output(sink,sink):
        print('script')
        thread=threading.Thread(target=lambda:print('unrelated'))
        thread.start();thread.join()
        nested=io.StringIO()
        with capture_output(nested,nested):print('nested')
        print('after')
    assert sink.getvalue()=='script\nafter\n'
    assert nested.getvalue()=='nested\n'
    assert original.getvalue()=='unrelated\n'
    assert sys.stdout is original


def test_structured_terminal_status():
    from server.application.command.command_execution_pipeline import CommandExecutionPipeline
    from server.application.tasks.task_status import TaskStreamSummary
    event=CommandExecutionPipeline.build_output_event(0,{'event_type':'error','failure_reason':'timed_out','text':'before\nScript timed out'})
    assert event.payload['failure_reason']=='timed_out'
    summary=TaskStreamSummary();summary.mark_dispatch_failure(event.payload['failure_reason'])
    assert summary.resolve_final_status()=='timed_out'
    summary=TaskStreamSummary();summary.mark_cancelled()
    assert summary.resolve_final_status()=='cancelled'
