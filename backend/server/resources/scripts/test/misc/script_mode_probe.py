SCRIPT_METADATA = {
    'name': "test/misc/script_mode_probe",
    'display_name': 'Script Mode Probe',
    'platforms': ['*'],
    'execution': {
        'modes': {'allowed': ['inproc', 'subprocess_pipe'], 'default': 'inproc'},
        'output': {'allowed': ['collect', 'stream'], 'default': 'collect'},
    },
    'params': [
        {'name': 'count', 'type': 'integer', 'default': 3, 'min': 1, 'max': 1000},
        {'name': 'delay', 'type': 'integer', 'default': 1, 'min': 0, 'max': 10},
    ],
}
import os, sys, time
print('pid', os.getpid(), flush=True)
for i in range(1, kwargs['count'] + 1):
    print('行', i, flush=True)
    time.sleep(kwargs['delay'])
print('', flush=True)
print('stderr warning', file=sys.stderr, flush=True)
print('tail', end='', flush=True)