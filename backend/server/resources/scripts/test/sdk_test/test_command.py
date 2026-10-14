SCRIPT_METADATA = {
    "display_name": "Command Test",
    "params": [],
    "api_grants": []
}

import os
import sys
import tempfile

from client.runtime.sdk import command
from client.runtime.sdk.command import BackgroundProcess, ShellResult, ScriptSdkCommandError


result = command.run_shell("whoami")
print('result =', result)
print('returncode =', result.returncode)
print('stdout =', result.stdout.strip())
print('stderr =', result.stderr.strip())

proc = command.run_shell("ping -c 6 127.0.0.1", background=True)
print('background proc =', proc)
print('background pid =', proc.pid)

result = command.run_client("getinfo")
print('getinfo ok =', result.ok)
print('getinfo status =', result.status)
print('getinfo output preview =', str(result.output))