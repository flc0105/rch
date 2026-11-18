SCRIPT_METADATA = {
    'name': 'common/terminal/batch_commands',
    'display_name': 'Batch Client Commands',
    'description': 'Run a JSON array of Client SDK commands and OS shell commands in order.',
    'category': 'Terminal',
    'platforms': ['mac', 'win', 'linux'],
    'execution': {
        'modes': {'allowed': ['inproc'], 'default': 'inproc'},
        'output': {'allowed': ['collect', 'stream'], 'default': 'stream'},
    },
    'params': [
        {
            'name': 'steps_json', 'label': 'Commands (JSON array)',
            'type': 'textarea', 'required': True,
            'default': '[\n  {"type": "client", "name": "cd", "args": ["."]},\n  {"type": "shell", "command": "echo RCH_SHELL_OK"},\n  {"type": "client", "name": "pyexec", "args": ["print(\'RCH_PY_OK\')"]},\n  {"type": "shell", "command": "whoami"}\n]',
        },
        {
            'name': 'stop_on_error', 'label': 'Stop on first error',
            'type': 'boolean', 'control': 'switch', 'required': False,
            'default': True,
        },
    ],
}

import json
import subprocess
import time

from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.runtime.sdk import command


def parse_steps(raw):
    try:
        steps = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'Invalid commands JSON: {exc}') from exc
    if not isinstance(steps, list) or not steps:
        raise ValueError('Commands must be a non-empty JSON array')

    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict) or step.get('type') not in ('client', 'shell'):
            raise ValueError(f'Step {index}: type must be "client" or "shell"')
        if step['type'] == 'client':
            if set(step) - {'type', 'name', 'args'}:
                raise ValueError(f'Step {index}: unexpected Client command fields')
            if not isinstance(step.get('name'), str) or not step['name'].strip():
                raise ValueError(f'Step {index}: Client command name is required')
            if not isinstance(step.get('args', []), list):
                raise ValueError(f'Step {index}: args must be an array')
        else:
            if set(step) != {'type', 'command'}:
                raise ValueError(f'Step {index}: Shell requires only type and command')
            if not isinstance(step['command'], str) or not step['command'].strip():
                raise ValueError(f'Step {index}: Shell command is required')
    return steps


def display(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return '' if value is None else str(value)


def run_batch():
    steps = parse_steps(kwargs['steps_json'])
    stop_on_error = kwargs['stop_on_error']
    passed = failed = 0
    print(f'Batch: {len(steps)} steps | Stop on error: {"yes" if stop_on_error else "no"}', flush=True)

    for index, step in enumerate(steps, 1):
        print(f'\n[{index}/{len(steps)}] > {json.dumps(step, ensure_ascii=False)}', flush=True)
        started = time.monotonic()
        try:
            if step['type'] == 'client':
                result = command.run_client(step['name'], *step.get('args', []))
                ok = result.ok  # Client command success is status=1.
                output = display(result.output)
                if output:
                    print(output, flush=True)
            else:
                result = command.run_shell(step['command'])
                ok = result.ok  # OS shell success is returncode=0.
                if result.stdout:
                    print(result.stdout, end='' if result.stdout.endswith('\n') else '\n', flush=True)
                if result.stderr:
                    print('[stderr]', flush=True)
                    print(result.stderr, end='' if result.stderr.endswith('\n') else '\n', flush=True)
                if not ok:
                    print(f'Shell exit code: {result.returncode}', flush=True)
        except (CommandCancelledError, CommandTimeoutError, subprocess.TimeoutExpired):
            raise  # Preserve the Script's cancellation/timeout state.
        except Exception as exc:
            ok = False
            print(f'{type(exc).__name__}: {exc}', flush=True)

        print(f'Result: {"SUCCESS" if ok else "ERROR"} | {time.monotonic() - started:.2f}s', flush=True)
        if ok:
            passed += 1
        else:
            failed += 1
            if stop_on_error:
                break

    skipped = len(steps) - passed - failed
    print(f'\nBatch finished: {passed} passed, {failed} failed, {skipped} skipped.', flush=True)
    if failed:
        raise RuntimeError(f'Batch failed: {failed} step(s) failed')


run_batch()
