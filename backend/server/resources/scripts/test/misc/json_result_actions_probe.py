SCRIPT_METADATA = {
    'name': 'test/misc/json_result_actions_probe',
    'display_name': 'JSON Result Actions Probe',
    'description': 'Safe JSON Viewer action confirmation, refresh, and Script Run Again probe.',
    'category': 'Test',
    'tags': ['test', 'json', 'actions'],
    'platforms': ['*'],
    'execution': {
        'modes': {'allowed': ['inproc', 'subprocess_pipe'], 'default': 'inproc'},
        'output': {'allowed': ['collect'], 'default': 'collect'},
    },
    'params': [],
}

import json
import tempfile
from pathlib import Path

# A temporary file on the target Client survives Script reruns. The query
# itself is read-only; only explicit row actions change this isolated value.
state = Path(tempfile.gettempdir()) / 'rch_json_result_actions_probe_counter.txt'
try:
    count = int(state.read_text(encoding='utf-8')) if state.exists() else 0
except (ValueError, OSError):
    count = 0

# This command runs on the same Client through the normal pyexec path.
# Repr keeps the cross-platform temporary path a valid Python string literal.
path_literal = repr(str(state))
increment = (
    'pyexec from pathlib import Path; '
    f'p = Path({path_literal}); '
    "p.write_text(str(int(p.read_text()) + 1 if p.exists() else 1))"
)
reset = (
    'pyexec from pathlib import Path; '
    f'p = Path({path_literal}); '
    'p.unlink() if p.exists() else None'
)

print(json.dumps([{
    'test': 'JSON Viewer actions',
    'counter': count,
    'hint': 'Use a refresh action, then compare with No Refresh and Run Again',
    '_actions': [
        {'label': 'Increment + Refresh', 'command': increment, 'confirm': False, 'refresh': True},
        {'label': 'Increment (No Refresh)', 'command': increment, 'confirm': False, 'refresh': False},
        {'label': 'Reset + Confirm', 'command': reset, 'confirm': True, 'refresh': True},
        {'label': 'Inspect PID', 'command': 'getpid', 'confirm': True, 'refresh': False},
    ],
}], ensure_ascii=False))
