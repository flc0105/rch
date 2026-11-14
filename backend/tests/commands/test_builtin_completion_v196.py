"""Completion integration smoke test with optional Web imports isolated in subprocess."""
import os
import subprocess
import sys
from pathlib import Path


def test_all_touched_builtin_completions():
    code = r'''
import sys, types
from types import SimpleNamespace as SN
fake=types.ModuleType('server.config.config')
fake.SCRIPT_PATH='backend/server/resources/scripts'
fake.COMMAND_HISTORY_RECENT_LIMIT=100
sys.modules['server.config.config']=fake
from server.application.completion.command_completion_providers import (
    ConfigCommandCompletionProvider, JobCommandCompletionProvider,
    ScriptCommandCompletionProvider, RegisteredServerSubcommandCompletionProvider,
    HistoryCommandCompletionProvider, RemoteClientCommandCompletionProvider)
from core.command_completion.models import CompletionContext
class Server:
    def get_target_connection_by_client_id(self, client_id):
        return SN(session_info=SN(os_alias='mac'))
class Remote:
    def __init__(self): self.calls=0
    def run_foreground_control(self, *args, **kwargs):
        self.calls+=1
        return 1,{'data':{'items':[{'key':'SCRIPT_DEFAULT_TIMEOUT','desc':'Seconds'}]}}
class BgJobs:
    def list_jobs(self, _):
        return [{'job_key':'active','state':'running'},{'job_key':'stopped','state':'stopped'}]
class Catalog:
    def list_background_job_catalog(self):
        return [{'job_name':name,'metadata':{'platforms':['darwin','linux']}}
                for name in ('active','idle','stopped')]
class History:
    def get_history_for_connection(self, conn):
        return [{'command':'whoami','is_pinned':True}, {'command':'pwd','is_pinned':False}]
def complete(provider, command, tail):
    ctx=CompletionContext(command_name=command, argument_text=tail, metadata={'client_id':'c'})
    return {item.insert_text for item in provider.complete(ctx)}
srv=Server(); remote=Remote()
cfg=ConfigCommandCompletionProvider(srv,remote)
for action in ('set','reset'):
    for marker in ('','--key '):
        assert f'config {action} {marker}SCRIPT_DEFAULT_TIMEOUT' in complete(cfg,'config',f'{action} {marker}')
assert remote.calls==1, remote.calls
job=JobCommandCompletionProvider(srv,Catalog(),BgJobs())
for marker in ('','--name '):
    start=complete(job,'job',f'start {marker}')
    assert f'job start {marker}idle' in start
    assert f'job start {marker}stopped' in start
    assert f'job start {marker}active' not in start
    for action in ('stop','status','logs'):
        results=complete(job,'job',f'{action} {marker}')
        assert results=={f'job {action} {marker}active'}, (action,results)
script=ScriptCommandCompletionProvider(srv)
for action in ('view','exec'):
    for marker in ('','--name '):
        assert any(item.startswith(f'script {action} {marker}') for item in
                   complete(script,'script',f'{action} {marker}'))
sub=RegisteredServerSubcommandCompletionProvider()
for root, cmd in (('config','config set'),('job','job status'),('script','script exec'),
                  ('history','history run')):
    assert any(item.startswith(cmd) for item in complete(sub,root,''))
assert RemoteClientCommandCompletionProvider.command_names==('cd','download','edit')
print('COMPLETION_OK')
'''
    root = Path(__file__).resolve().parents[3]
    env = {**os.environ, 'PYTHONPATH': str(root / 'backend')}
    p = subprocess.run([sys.executable, '-c', code], cwd=root, env=env, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert 'COMPLETION_OK' in p.stdout
