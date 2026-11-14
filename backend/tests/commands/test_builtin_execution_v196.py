"""Exercise the migrated builtin Supports while isolating optional Web dependencies."""
import os
import subprocess
import sys
from pathlib import Path


def test_script_history_rtt_watchdog_end_to_end_of_support_layer(tmp_path):
    root = Path(__file__).resolve().parents[3]
    script = r'''
import json, sys, types
from types import SimpleNamespace as NS
config=types.ModuleType('server.config.config')
config.SCRIPT_PATH='backend/server/resources/scripts'
config.COMMAND_HISTORY_RECENT_LIMIT=100
sys.modules['server.config.config']=config
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY as reg
from server.application.command.builtin_command_support import HistoryBuiltinSupport, RttBuiltinSupport, ScriptBuiltinSupport
from server.application.command.configuration_builtin_support import ConfigurationBuiltinSupport
from core.protocol.message_queue import ResultChunk

class Store:
    def __init__(self):
        self.recent=['pwd']; self.pinned=['whoami']; self.clears=0
    def get_history_for_connection(self,_):
        return ([{'command':cmd,'is_pinned':True} for cmd in self.pinned] +
                [{'command':cmd,'is_pinned':False} for cmd in self.recent])
    def clear_history_for_connection(self,_):
        self.clears+=1;self.recent=[]
store=Store()
class Processor:
    def __call__(self,command):return lambda: iter([(1,'inner:'+command)])
history=HistoryBuiltinSupport(store,NS(),lambda:None,lambda:Processor())
rows=list(history.history(reg.parse_invocation('history','list --json')))
assert rows[0][0]==1 and len(json.loads(rows[0][1]))==2
rows=list(history.history(reg.parse_invocation('history','list -p --json')))
assert [r['command'] for r in json.loads(rows[0][1])]==['whoami']
rows=list(history.history(reg.parse_invocation('history','run --index 2')))
assert rows[1]==(1,'inner:pwd'),rows
assert 'sending command: pwd' in rows[0][1]
assert 'cleared' in list(history.history(reg.parse_invocation('history','clear')))[0][1]
assert store.clears==1 and store.pinned==['whoami'] and store.recent==[]

rtt=RttBuiltinSupport(NS(context=NS(connected_at='then',disconnected_at='',
    last_seen_at='',last_heartbeat_sent_at='',last_heartbeat_ack_at='',last_rtt_ms=12,
    last_heartbeat_id=7)))
flat=list(rtt.rtt(reg.parse_invocation('rtt','')))[0][1]
assert 'last_rtt_ms' in flat and '12' in flat
raw=list(rtt.rtt(reg.parse_invocation('rtt','--json')))[0][1]
assert json.loads(raw)['last_rtt_ms']==12

watchdog=ConfigurationBuiltinSupport(NS(),NS(),lambda:None)
watchdog._send=lambda *a: iter([ResultChunk(1, {'remote_control_watchdog': {'enabled':True}}, True)])
text=list(watchdog.watchdog(reg.parse_invocation('watchdog','')))[0][1]
assert 'remote_control_watchdog' in text
structured=list(watchdog.watchdog(reg.parse_invocation('watchdog','--json')))[0][1]
assert json.loads(structured)['remote_control_watchdog']['enabled'] is True
watchdog._send=lambda *a: iter([ResultChunk(0, 'Client unavailable', True)])
assert json.loads(list(watchdog.watchdog(reg.parse_invocation('watchdog','--json')))[0][1]) == {
    'status':'error','message':'Client unavailable'}

script_support=ScriptBuiltinSupport(None,None)
script_support.list_script_catalog=lambda: [
  {'path':'demo.py','display_name':'demo','description':'test','metadata':{'params':[{'name':'count'}]}}]
records=list(script_support.script(reg.parse_invocation('script','list --json')))
assert json.loads(records[0][1])==[{'name':'demo.py','display_name':'demo','description':'test','params':['count']}]
records=list(script_support.script(reg.parse_invocation('script','list')))
assert 'demo.py' in records[0][1]
script_support._resolve_script_path=lambda name: sys.argv[1]
assert 'print(1)' in list(script_support.script(reg.parse_invocation('script','view --name demo.py')))[0][1]
print('BUILTIN_EXECUTION_OK')
'''
    demo = tmp_path / 'demo.py'
    demo.write_text('print(1)\n', encoding='utf-8')
    result = subprocess.run([sys.executable, '-c', script, str(demo)], cwd=root,
        env={**os.environ,'PYTHONPATH':str(root/'backend')}, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'BUILTIN_EXECUTION_OK' in result.stdout
