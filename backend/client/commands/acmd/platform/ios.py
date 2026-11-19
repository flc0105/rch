"""Pythonista-only structured commands."""
import os
from collections import deque
from itertools import islice

from client.commands.acmd.decorators import argument_command
from client.commands.platform.utils.ios_util import show_ios_alert
from core.command_completion.models import CompletionSpec
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec


ALERT_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='alert',
    description='Show alert dialog',
    options=[
        ArgumentOptionSpec('title', 'str', default='Alert', help_text='Dialog title'),
        ArgumentOptionSpec('message', 'str', required=True, allow_empty=False, help_text='Dialog text'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
)

TREE_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='tree',
    description='Show directory tree',
    options=[
        ArgumentOptionSpec('path', 'str', default='.', positional_index=0, help_text='Target directory',
                           completion=CompletionSpec('filesystem', ('directory',))),
        ArgumentOptionSpec('max_depth', 'int', default=3, alias='L', help_text='Maximum recursion depth'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
)

HEAD_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='head',
    description='Show first N lines of a text file',
    options=[
        ArgumentOptionSpec('path', 'str', required=True, allow_empty=False, positional_index=0,
                           completion=CompletionSpec('filesystem', ('file', 'directory')), help_text='Text file path'),
        ArgumentOptionSpec('lines', 'int', default=10, alias='n', help_text='Number of lines to show'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
)

TAIL_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='tail',
    description='Show last N lines of a text file',
    options=[
        ArgumentOptionSpec('path', 'str', required=True, allow_empty=False, positional_index=0,
                           completion=CompletionSpec('filesystem', ('file', 'directory')), help_text='Text file path'),
        ArgumentOptionSpec('lines', 'int', default=10, alias='n', help_text='Number of lines to show'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
)


class iOSACMDCommands:
    @argument_command('alert', spec=ALERT_ARGUMENT_SPEC)
    def alert(self, args_dict):
        try:
            button = show_ios_alert(args_dict['title'] or 'Alert', args_dict['message'])
            return 1, f'Alert closed: {button}'
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            return 0, f'Failed to show alert: {exc}'

    @argument_command('tree', spec=TREE_ARGUMENT_SPEC)
    def tree(self, args_dict):
        depth_limit = args_dict['max_depth']
        if depth_limit < 0:
            return 0, 'Option "--max_depth" must be >= 0'
        try:
            target = self.path_resolver.require_existing_directory(args_dict['path'])
            lines = [os.path.basename(target) or target]
            pending = [(target, '', '', 0)]
            while pending:
                path, prefix, line, depth = pending.pop()
                self._checkpoint()
                if line:
                    lines.append(line)
                if depth >= depth_limit or (depth and os.path.islink(path)) or not os.path.isdir(path):
                    continue
                with os.scandir(path) as scan:
                    entries = sorted(scan, key=lambda entry: (not entry.is_dir(), entry.name.casefold()))
                for index in range(len(entries) - 1, -1, -1):
                    entry = entries[index]
                    last = index == len(entries) - 1
                    branch = '└── ' if last else '├── '
                    suffix = '/' if entry.is_dir() else ''
                    pending.append((entry.path, prefix + ('    ' if last else '│   '),
                                    f'{prefix}{branch}{entry.name}{suffix}', depth + 1))
            return 1, '\n'.join(lines)
        except OSError as exc:
            return 0, f'tree failed: {exc}'

    @argument_command('head', spec=HEAD_ARGUMENT_SPEC)
    def head(self, args_dict):
        count = args_dict['lines']
        if count < 0:
            return 0, 'Option "--lines" must be >= 0'
        try:
            path = self.path_resolver.require_existing_file(args_dict['path'])
            with open(path, encoding='utf-8', errors='ignore') as stream:
                return 1, ''.join(islice(stream, count)).rstrip('\n')
        except (OSError, ValueError, OverflowError) as exc:
            return 0, f'head failed: {exc}'

    @argument_command('tail', spec=TAIL_ARGUMENT_SPEC)
    def tail(self, args_dict):
        count = args_dict['lines']
        if count < 0:
            return 0, 'Option "--lines" must be >= 0'
        try:
            path = self.path_resolver.require_existing_file(args_dict['path'])
            if not count:
                return 1, ''
            with open(path, encoding='utf-8', errors='ignore') as stream:
                return 1, ''.join(deque(self._iter_checked(stream, check_interval=256), maxlen=count)).rstrip('\n')
        except (OSError, ValueError, OverflowError) as exc:
            return 0, f'tail failed: {exc}'
