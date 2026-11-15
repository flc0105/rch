"""Canonical Client/Server Result wire + consumer projection contract."""
import json
from types import SimpleNamespace

import pytest

from core.protocol.message_queue import ResultChunk, result_terminal_status
from core.protocol.result_envelope import ResultEnvelope, result_wire_event
from core.utils.command_output import render_result_payload
from server.application.command.command_execution_pipeline import CommandExecutionPipeline
from server.application.command.configuration_builtin_support import ConfigurationBuiltinSupport
from server.connection.runtime.pending_results import PendingResults
from server.connection.services.message_router import ServerInboundMessageRouter


def test_wire_lifecycle_no_display_eof_or_nonterminal_status():
    start = result_wire_event(18, 1, 'Started', final=False, event_type='progress')
    assert result_wire_event(18, 1, '', final=False, event_type='started')['event_type'] == 'started'
    msg = result_wire_event(18, 1, {'event_type': 'chunk', 'data': {'a': 1}}, final=False)
    done = result_wire_event(18, 1, ResultEnvelope(message='Finished', data={'n': 2}).as_payload())
    assert (start['event_type'], msg['event_type'], done['event_type']) == ('progress','chunk','completed')
    assert 'status' not in start and 'status' not in msg
    assert done['status'] == 'success'
    assert done['data'] == {'n': 2}
    for packet in (start,msg,done):
        assert packet['type'] == 'result' and packet['id'] == 18
        assert 'display' not in packet and 'eof' not in packet and 'shape' not in packet
    assert result_wire_event(18,1,{'event_type':'completed','message':'not final'}, final=False)['event_type'] == 'chunk'


def test_wire_list_empty_failure_and_partial():
    empty = result_wire_event(12,1,{'event_type':'completed','status':'success','message':'No jobs','data':[]})
    assert empty['data'] == []
    failed = result_wire_event(12,0,ResultEnvelope(status='error', message='Denied').as_payload())
    assert failed['status'] == 'error' and 'data' not in failed
    partial = result_wire_event(12,0,ResultEnvelope(status='partial', data={'ok':1,'failed':1}).as_payload())
    assert partial['status'] == 'partial' and partial['data']['failed'] == 1
    with pytest.raises(ValueError):
        ResultEnvelope(data='JSON encoded text').as_payload()


def test_inbound_delivers_full_array_and_only_first_completed_finishes():
    pending = PendingResults()
    q = pending.register(77)
    class Dispatcher:
        def dispatch_result(self, id, event, before_enqueue):
            return pending.deliver(id, event, before_enqueue)
    sent=[]
    conn=SimpleNamespace(update_current_workdir=lambda cwd: sent.append(cwd),
                         services=SimpleNamespace(result_dispatcher=Dispatcher()),
                         context=SimpleNamespace(on_client_message_received=lambda *_: None))
    router=ServerInboundMessageRouter(conn)
    progress={'type':'result','id':77,'event_type':'progress','message':'Loading','cwd':'/tmp'}
    completed={'type':'result','id':77,'event_type':'completed','status':'success','data':[{'pid':5}]}
    router.handle_result_message(progress)
    router.handle_result_message(completed)
    router.handle_result_message({**completed,'data':[]})
    rows=[q.get(False),q.get(False)]
    assert rows[0]['event_type'] == 'progress' and rows[1]['event_type'] == 'completed'
    assert rows[1]['data']==[{'pid':5}]
    assert q.empty() and sent==['/tmp',None]


def test_table_flat_grouped_and_cli_projection_share_facts():
    raw={'store_path':'/x','items':[{'group':'general','key':'timeout','value':10,
        'default_value':5,'desc':'terminal does not show this','editable':True}]}
    from core.utils.configuration_cli import configuration_cli_items
    projection=configuration_cli_items(raw)
    result=ResultEnvelope(data=projection).as_payload()
    assert json.loads(render_result_payload(result,'json',view='data',shape='table')) == projection
    text=render_result_payload(result,'text',view='data',shape='table')
    assert 'group' in text and 'timeout' in text and 'terminal does not show this' not in text
    assert list(projection[0])==['group','key','value','default']
    assert 'editable' in raw['items'][0]
    flat=render_result_payload(ResultEnvelope(data={'state':'running'}).as_payload(),view='data',shape='flat')
    assert 'state' in flat and 'running' in flat
    grouped=render_result_payload(ResultEnvelope(data={'client':{'ready':True},'watchdog':{'active':False}}).as_payload(),view='data',shape='grouped')
    assert '[client]' in grouped and '[watchdog]' in grouped


def test_canonical_terminal_event_preserves_raw_event_for_sse():
    raw={'type':'result','id':21,'event_type':'completed','status':'success','data':[{'x':1}]}
    item=ResultChunk(1, raw, True, terminal_authoritative=True, event=raw)
    event=CommandExecutionPipeline.build_result_event(item)
    assert event.payload['result_envelope'] is raw
    assert event.payload['result_terminal']=='success'
    assert 'x' in event.text


def test_configuration_builtin_projection_preserves_web_raw():
    raw={'store_path':'/cfg','items':[{'group':'g','key':'k','value':2,'default_value':1,
                                     'desc':'metadata','editable':True,'value_type':'integer'}]}
    packet={'type':'result','id':42,**ResultEnvelope(data=raw).as_payload()}
    class Remote:
        def stream_command(self,*_,**__):
            yield ResultChunk(1,packet,True,event=packet)
    support=ConfigurationBuiltinSupport(None, Remote(), lambda: '')
    inv=SimpleNamespace(action='list',arguments={},output_format='json')
    rows=list(support.config(inv))
    assert len(rows)==1 and rows[0].event is packet
    assert json.loads(rows[0][1])==[{'group':'g','key':'k','value':2,'default':1}]
    assert 'desc' in packet['data']['items'][0]  # Web fact source left intact


def test_error_message_does_not_render_empty_table():
    error=ResultEnvelope(status='error',message='Permission denied',data=[]).as_payload()
    assert render_result_payload(error,view='data',shape='table')=='Permission denied'
    assert json.loads(render_result_payload(error,'json',view='data'))=={'status':'error','message':'Permission denied'}
    assert result_terminal_status(0,error)=='error'


def test_watchdog_control_raw_data_renders_grouped_at_calling_side():
    data={'client':{'state':'running'},'remote_control_watchdog':{'enabled':True}}
    packet={'type':'result','id':19,'event_type':'completed','status':'success','data':data}
    class Remote:
        def stream_command(self,*_,**__):
            yield ResultChunk(1,packet,True,event=packet)
    support=ConfigurationBuiltinSupport(None, Remote(), lambda:'')
    inv=SimpleNamespace(output_format='text')
    output=list(support.watchdog(inv))
    assert len(output)==1 and output[0].event is packet
    assert '[client]' in output[0][1] and '[remote_control_watchdog]' in output[0][1]
    json_output=list(support.watchdog(SimpleNamespace(output_format='json')))
    assert json.loads(json_output[0][1])==data
