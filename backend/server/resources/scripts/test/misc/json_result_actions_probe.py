SCRIPT_METADATA = {
    'name': 'test/misc/json_result_actions_probe',
    'display_name': 'JSON Result Actions Probe',
    'description': 'Test Script emit_view, cross-Script actions, confirmation, and rerun.',
    'category': 'Test',
    'tags': ['test', 'json', 'actions'],
    'platforms': ['*'],
    'execution': {
        'modes': {'allowed': ['inproc', 'subprocess_pipe'], 'default': 'inproc'},
        'output': {'allowed': ['collect', 'stream'], 'default': 'collect'},
    },
    'params': [],
}

from datetime import datetime
import os
from client.runtime.sdk import context

# Rerunning this Script changes the timestamp. No setup or files are needed.
context.emit_view([{
    'name': 'Current Python Client',
    'pid': os.getpid(),
    'checked_at': datetime.now().astimezone().isoformat(timespec='microseconds'),
}], view={
    'titleField': 'name',
    'actions': [
        {
            'label': 'Run Child + Refresh',
            'command': 'script exec test/misc/json_result_actions_update',
            'confirm': False,
            'refresh': True,
        },
        {
            'label': 'Run Child (No Refresh)',
            'command': 'script exec test/misc/json_result_actions_update',
            'confirm': False,
            'refresh': False,
        },
        {
            'label': 'Run Child + Confirm',
            'command': 'script exec test/misc/json_result_actions_update',
            'confirm': True,
            'refresh': True,
        },
        {
            'label': 'Inspect PID',
            'command': 'getpid',
            'confirm': True,
            'refresh': False,
        },
    ],
})
