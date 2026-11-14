"""Verify both Server completion name forms with a simulated Client GET."""
import os
import subprocess
import sys
from pathlib import Path


def test_config_script_named_completion_without_optional_server_web_deps():
    root = Path(__file__).resolve().parents[3]
    code = r'''
import sys, types
from types import SimpleNamespace as NS
config=types.ModuleType('server.config.config')
config.SCRIPT_PATH = 'backend/server/resources/scripts'
config.COMMAND_HISTORY_RECENT_LIMIT=100
sys.modules['server.config.config']=config
from core.command_completion.models import CompletionContext
from server.application.completion.command_completion_providers import (
  ConfigCommandCompletionProvider, ScriptCommandCompletionProvider)
class Remote:
    calls=0
    def run_foreground_control(self, client_id, domain, action, params, **kw):
        self.calls += 1
        return 1, {'data':{'items':[{'key':'SCRIPT_DEFAULT_TIMEOUT','desc':'Script timeout'}]}}
remote=Remote()
config_provider=ConfigCommandCompletionProvider(NS(), remote)
for argument, expected in [
    ('set ', 'config set SCRIPT_DEFAULT_TIMEOUT'),
    ('set --key ', 'config set --key SCRIPT_DEFAULT_TIMEOUT'),
    ('reset ', 'config reset SCRIPT_DEFAULT_TIMEOUT'),
    ('reset --key ', 'config reset --key SCRIPT_DEFAULT_TIMEOUT')]:
    context=CompletionContext(command_name='config', argument_text=argument,
                              metadata={'client_id':'client-1'})
    assert expected in [item.insert_text for item in config_provider.complete(context)]
assert remote.calls==1, remote.calls
script_provider=ScriptCommandCompletionProvider(NS())
script_provider._list_scripts=lambda platform: ['test/misc/script_mode_probe']
for argument, expected in [
    ('view ', 'script view test/misc/script_mode_probe'),
    ('view --name ', 'script view --name test/misc/script_mode_probe'),
    ('exec ', 'script exec test/misc/script_mode_probe'),
    ('exec --name ', 'script exec --name test/misc/script_mode_probe')]:
    context=CompletionContext(command_name='script', argument_text=argument)
    assert expected in [item.insert_text for item in script_provider.complete(context)]
print('SERVER_NAMED_COMPLETION_OK')
'''
    result = subprocess.run([sys.executable, '-c', code], cwd=root,
        env={**os.environ, 'PYTHONPATH': str(root / 'backend')},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'SERVER_NAMED_COMPLETION_OK' in result.stdout
