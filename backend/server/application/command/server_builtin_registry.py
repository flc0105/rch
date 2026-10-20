"""Single explicit source of Server builtin names, subcommands, help and completion.

Business implementations stay in their existing support classes.  The parser
preserves raw tails for alias templates, shell-like arguments and structured JSON.
Unknown commands are deliberately *not* claimed: they can reach the Client Shell.
"""
from dataclasses import dataclass
import re
import shlex


@dataclass(frozen=True)
class SubcommandSpec:
    name: str
    description: str
    usage: str = ''
    visibility: str = 'public'
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    handler: str
    subcommands: tuple[SubcommandSpec, ...] = ()
    default: str = ''
    allow_direct: bool = False
    suggest: bool = True
    group: str = 'server'
    expects_arguments: bool = False

    def child(self, name):
        return next((item for item in self.subcommands if item.name == name), None)


def command(name, description, handler=None, children=(), default='', allow_direct=False, group='server', expects_arguments=False):
    return CommandSpec(name, description, handler or name,
                       tuple(SubcommandSpec(*item) for item in children),
                       default, allow_direct, True, group, expects_arguments)


SERVER_COMMAND_SPECS = (
    command('upload', 'Upload a local file to the Client', expects_arguments=True),
    command('script', 'List, inspect and run Server scripts', children=(
        ('list', 'List available scripts (optionally --json)', 'script list [--json]'),
        ('view', 'Read script source on the Server', 'script view <path>'),
        ('exec', 'Execute a script with CLI arguments', 'script exec <path> [options]'),
        ('run', 'Execute a script with structured JSON payload', 'script run <__json__:payload>'),
    ), default='list', group='script'),
    command('alias', 'List or manage aliases for this Client platform', children=(
        ('list', 'List current effective aliases (optionally --json)', 'alias list [--json]'),
        ('set', 'Save an alias', 'alias set [--platform PLATFORM] name = command'),
        ('unset', 'Remove an alias', 'alias unset [--platform PLATFORM] name'),
    ), default='list', group='alias'),
    command('job', 'Manage Client jobs from the Server', children=(
        ('list', 'List available Server jobs (optionally --json)', 'job list [--json]'),
        ('start', 'Start a Client job', 'job start <name> [--mode MODE] [--params JSON]', 'public', ('mode','params')),
        ('ps', 'Show running jobs', 'job ps'),
        ('status', 'Query job state', 'job status <name>'),
        ('stop', 'Stop a running job', 'job stop <name>'),
        ('stop-all', 'Stop all running jobs', 'job stop-all'),
    ), default='list', group='job'),
    command('history', 'Show Quick History or replay by index', children=(
        ('list', 'Display Quick History', 'history'),
        ('clear', 'Clear Quick Recent', 'history clear'),
        ('run', 'Replay a Quick command by index', 'history run <index>'),
    ), default='list', group='history'),
    command('gopin', 'Jump to saved path', expects_arguments=True),
    command('rtt', 'Show current heartbeat RTT'),
    command('httpctl', 'Client HTTP control channel', children=(
        ('kill', 'Terminate current Agent', 'httpctl kill'),
        ('relaunch', 'Relaunch Agent', 'httpctl relaunch'),
        ('clone', 'Clone Agent', 'httpctl clone'),
        ('help', 'Show HTTP control usage', 'httpctl help'),
    ), default='help', group='control'),
    command('saveout', 'Save Client command output as Artifact', expects_arguments=True),
    command('notify', 'Run a Client command and notify when finished', expects_arguments=True),
    command('xt', 'External tool catalog and execution', children=(
        ('list', 'List external tools', 'xt list'),
        ('info', 'Show external tool details', 'xt info <name>'),
        ('which', 'Locate external executable', 'xt which <name>'),
        ('run', 'Execute external tool', 'xt run <name> [--] [args]'),
    ), default='list', allow_direct=True, group='external_tool'),
    command('help', 'Show Server builtin commands and subcommands', handler='server_help'),
)


class ServerCommandRegistry:
    def __init__(self, definitions=SERVER_COMMAND_SPECS):
        self._commands = {spec.name: spec for spec in definitions}
        if len(self._commands) != len(definitions):
            raise ValueError('Duplicate server builtin command name')

    def get(self, name):
        return self._commands.get(str(name or '').lower())

    def parse(self, name, raw_arg):
        """Parse subcommand once while keeping its raw argument tail unmodified.

        Returns (spec, subcommand, tail), where subcommand is None for
        non-hierarchical commands. No unknown name is swallowed by the Server.
        """
        spec = self.get(name)
        if spec is None:
            return None
        if not spec.subcommands:
            return spec, None, str(raw_arg or '')
        text = str(raw_arg or '').strip()
        if not text:
            return spec, spec.default, ''
        match = re.match(r'^(\S+)(?:\s+(.*))?$', text, re.DOTALL)
        token, tail = match.group(1).lower(), match.group(2) or ''
        if spec.child(token):
            return spec, token, tail
        # Default list commands support --json without repeating `list`.
        if token == '--json' and spec.default == 'list':
            return spec, 'list', text
        if spec.allow_direct:
            return spec, '__direct__', text
        raise ValueError(f'Unsupported {spec.name} subcommand: {token}. Use: {self.usage(spec.name)}')

    def parse_arguments(self, name, subcommand, raw_tail):
        """Shared shlex option parser for explicitly declared value-taking flags.

        Preserve the original tail for subcommands marked raw in their business
        support; no automatic re-serialization of shell templates or Base64 JSON.
        """
        spec = self.get(name)
        child = spec.child(subcommand) if spec else None
        if child is None:
            raise ValueError(f'Unknown subcommand: {name} {subcommand}')
        try:
            tokens = shlex.split(str(raw_tail or ''))
        except ValueError as exc:
            raise ValueError(f'Invalid {name} arguments: {exc}') from exc
        positionals, options = [], {}
        idx = 0
        while idx < len(tokens):
            token = tokens[idx]
            if token == '--':
                positionals.extend(tokens[idx + 1:])
                break
            if token.startswith('--'):
                key_value = token[2:].split('=', 1)
                key = key_value[0]
                if key not in child.options:
                    raise ValueError(f'Unknown option: --{key}')
                if key in options:
                    raise ValueError(f'Duplicate --{key}')
                if len(key_value) == 2:
                    value = key_value[1]
                else:
                    idx += 1
                    if idx >= len(tokens):
                        raise ValueError(f'Missing value for --{key}')
                    value = tokens[idx]
                options[key] = value
            else:
                positionals.append(token)
            idx += 1
        return positionals, options

    def usage(self, name):
        spec = self.get(name)
        if spec is None:
            raise ValueError(f'Unknown Server command: {name}')
        if not spec.subcommands:
            return f'{spec.name} — {spec.description}'
        return '\n'.join([f'{spec.name} — {spec.description}'] +
                         [f'  {item.usage or spec.name + " " + item.name} — {item.description}'
                          for item in spec.subcommands if item.visibility == 'public'])

    def help(self, target=''):
        target = str(target or '').strip().lower()
        if not target:
            return '\n'.join(f'{spec.name:<13} {spec.description}' for spec in self._commands.values())
        words = target.split()
        spec = self.get(words[0])
        if spec is None:
            raise ValueError(f'Unknown Server command: {words[0]}')
        if len(words) == 1:
            return self.usage(spec.name)
        sub = spec.child(words[1])
        if sub is None or len(words) != 2:
            raise ValueError(f'Unknown subcommand: {target}')
        return f'{sub.usage} — {sub.description}'

    def candidates(self):
        return [dict(name=spec.name, template=spec.name + (' ' if spec.subcommands or spec.expects_arguments else ''),
                     help=spec.description, source='server', group=spec.group,
                     suggest=spec.suggest,
                     subcommands=[dict(name=child.name, usage=child.usage,
                                       description=child.description)
                                  for child in spec.subcommands if child.visibility == 'public'])
                for spec in self._commands.values()]


SERVER_COMMAND_REGISTRY = ServerCommandRegistry()
