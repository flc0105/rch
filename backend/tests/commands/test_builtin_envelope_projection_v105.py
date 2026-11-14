"""Server-owned Builtins retain their data while producing unchanged CLI text."""
import os
from pathlib import Path
import subprocess
import sys


def test_builtin_one_shot_raw_events_without_reformatting(tmp_path):
    root = Path(__file__).resolve().parents[3]
    source = r'''
import json, sys, types
from types import SimpleNamespace as NS
config = types.ModuleType('server.config.config')
config.SCRIPT_PATH = 'backend/server/resources/scripts'
config.COMMAND_HISTORY_RECENT_LIMIT = 100
sys.modules['server.config.config'] = config
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY as reg
from server.application.command.builtin_command_support import ScriptBuiltinSupport, HistoryBuiltinSupport, RttBuiltinSupport, PinnedPathBuiltinSupport
from server.application.command.job_builtin_support import JobBuiltinSupport

def assert_result(item, data_type):
    assert item[0] == 1
    assert item.event['event_type'] == 'completed'
    assert item.event['status'] == 'success'
    assert isinstance(item.event['data'], data_type)
    assert item.terminal_authoritative is True

script = ScriptBuiltinSupport(None, None)
script.list_script_catalog = lambda: [{'path':'probe.py', 'display_name':'Probe', 'description':'Testing', 'metadata':{'params':[]}}]
item = next(script.script(reg.parse_invocation('script','list')))
assert 'probe.py' in item[1]
assert_result(item, list)
assert item.event['data'][0]['name'] == 'probe.py'

class Store:
 def get_history_for_connection(self, conn):return [{'command':'pwd','index':1,'is_pinned':False}]
 def clear_history_for_connection(self, conn):pass
history = HistoryBuiltinSupport(Store(), NS(),lambda:None,lambda:None)
item = next(history.history(reg.parse_invocation('history','list')))
assert 'Tip:' in item[1]
assert_result(item, list)
assert item.event['data'][0]['command'] == 'pwd'

rtt = RttBuiltinSupport(NS(context=NS(connected_at='now', disconnected_at='',last_seen_at='',last_heartbeat_sent_at='',last_heartbeat_ack_at='',last_rtt_ms=2,last_heartbeat_id=1)))
item = next(rtt.rtt(reg.parse_invocation('rtt','')))
assert 'last_rtt_ms' in item[1]
assert_result(item, dict)

pinned = PinnedPathBuiltinSupport.__new__(PinnedPathBuiltinSupport)
pinned.list_pinned_paths = lambda: [{'display_name':'home','path':'/tmp'}]
item = next(pinned.gopin(reg.parse_invocation('gopin','list')))
assert 'home' in item[1]
assert_result(item, list)

job = JobBuiltinSupport(None, NS(session_info=NS(os_alias='linux',client_id='client')),None,None,NS(list_background_job_catalog=lambda: [{'job_name':'example', 'display_name':'Example', 'description':'test', 'metadata':{'platforms':['linux']}}]))
item = next(job.execute_subcommand(reg.parse_invocation('job','list')))
assert 'example' in item[1]
assert_result(item, list)
print('V105_BUILTIN_ENVELOPE_OK')
'''
    result = subprocess.run([sys.executable, '-c', source], cwd=root, text=True,
                            env={**os.environ, 'PYTHONPATH': str(root / 'backend')},
                            capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'V105_BUILTIN_ENVELOPE_OK' in result.stdout
