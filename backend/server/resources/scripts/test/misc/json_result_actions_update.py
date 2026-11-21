SCRIPT_METADATA = {
    'name': 'test/misc/json_result_actions_update',
    'display_name': 'JSON Result Actions Child',
    'description': 'Show that a Viewer Action can run a second Script without parameters.',
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

print('Child Script executed successfully')
print('Python PID:', os.getpid())
print('Executed at:', datetime.now().astimezone().isoformat(timespec='microseconds'))
