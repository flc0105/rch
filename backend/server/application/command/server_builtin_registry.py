"""Single explicit source of Server builtin names, subcommands, help and completion.

Business implementations stay in their existing support classes.  The parser
preserves raw tails for alias templates, shell-like arguments and structured JSON.
Unknown commands are deliberately *not* claimed: they can reach the Client Shell.
"""
from dataclasses import dataclass
import re
import shlex

from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.commands.argument_parser import parse_argument_text
from core.commands.argument_errors import ArgumentCommandValidationError
from core.utils.command_output import OutputFormat


@dataclass(frozen=True)
class SubcommandSpec:
    name: str
    description: str
    usage: str = ''
    visibility: str = 'public'
    options: tuple[str, ...] = ()
    argument_spec: ArgumentCommandSpec | None = None


@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    handler: str
    subcommands: tuple[SubcommandSpec, ...] = ()
    default: str = ''
    dispatch_subcommand: bool = False
    suggest: bool = True
    group: str = 'server'
    expects_arguments: bool = False
    structured: bool = False

    def child(self, name):
        return next((item for item in self.subcommands if item.name == name), None)


def command(name, description, handler=None, children=(), default='', dispatch_subcommand=False, group='server', expects_arguments=False, structured=False):
    return CommandSpec(name, description, handler or name,
                       tuple(item if isinstance(item, SubcommandSpec) else SubcommandSpec(*item)
                             for item in children),
                       default, dispatch_subcommand, True, group, expects_arguments, structured)



def _option(name, *, positional=None, required=False, flag=False, alias='', arity=1, repeatable=False):
    return ArgumentOptionSpec(name=name, option_type='flag' if flag else 'str',
                              default=False if flag else ([] if repeatable else None),
                              required=required, positional_index=positional,
                              allow_empty=False, alias=alias, arity=arity,
                              repeatable=repeatable)


def _arguments(name, *options, json=True, trailing_named_arguments=None):
    return ArgumentCommandSpec(
        name, options=[*options, *([_option('json', flag=True)] if json else [])],
        trailing_named_arguments=trailing_named_arguments)


def _structured_child(command_name, action, description, usage, *options,
                      json=True, trailing_named_arguments=None):
    return SubcommandSpec(action, description, usage, argument_spec=_arguments(
        f'{command_name} {action}', *options, json=json,
        trailing_named_arguments=trailing_named_arguments))

SERVER_COMMAND_SPECS = (
    command('config', 'Show or update client runtime config', children=(
        _structured_child('config', 'list', 'List runtime config', 'config [list] [--json]'),
        _structured_child('config', 'set', 'Set one runtime config value',
                          'config set <key> <value> [--json]',
                          _option('key', positional=0, required=True),
                          _option('value', positional=1, required=True)),
        _structured_child('config', 'reset', 'Reset one runtime config value',
                          'config reset <key> [--json]', _option('key', positional=0, required=True)),
        _structured_child('config', 'reset-all', 'Reset all config overrides', 'config reset-all [--json]'),
    ), default='list', dispatch_subcommand=True, group='runtime', structured=True),
    command('watchdog', 'Show watchdog runtime status', expects_arguments=True, group='runtime'),
    command('upload', 'Upload a local file to the Client', expects_arguments=True),
    command('script', 'List, inspect and run Server scripts', children=(
        _structured_child('script', 'list', 'List available scripts', 'script list [--json]'),
        _structured_child('script', 'view', 'Read script source on the Server',
                          'script view <name>|--name NAME',
                          _option('name', positional=0, required=True), json=False),
        _structured_child('script', 'exec', 'Execute a script with CLI arguments',
                          'script exec <name>|--name NAME [--execution_mode MODE] [--output_mode MODE] [-- --key VALUE]...',
                          _option('name', positional=0, required=True),
                          _option('execution_mode'), _option('output_mode'),
                          json=False, trailing_named_arguments='params'),
    ), default='list', dispatch_subcommand=True, structured=True),
    command('alias', 'List or manage aliases for this Client platform', children=(
        ('list', 'List current effective aliases (optionally --json)', 'alias list [--json]'),
        ('set', 'Save an alias', 'alias set [--platform PLATFORM] name = command'),
        ('unset', 'Remove an alias', 'alias unset [--platform PLATFORM] name'),
    ), default='list', dispatch_subcommand=True),
    command('job', 'Manage Client jobs from the Server', children=(
        _structured_child('job', 'list', 'List available Server jobs', 'job list [--json]'),
        _structured_child('job', 'start', 'Start a Client job',
                          'job start <name>|--name NAME [--mode MODE] [--json] [-- --key VALUE]...',
                          _option('name', positional=0, required=True), _option('mode'),
                          trailing_named_arguments='params'),
        _structured_child('job', 'logs', 'Read stored Job reports or follow new reports',
                          'job logs <name> [--follow|-f]',
                          _option('name', positional=0, required=True),
                          _option('follow', flag=True, alias='f'), json=False),
        _structured_child('job', 'ps', 'Show running jobs', 'job ps [--json]'),
        _structured_child('job', 'status', 'Query job state', 'job status <name> [--json]',
                          _option('name', positional=0, required=True)),
        _structured_child('job', 'stop', 'Stop a running job', 'job stop <name> [--json]',
                          _option('name', positional=0, required=True)),
        _structured_child('job', 'stop-all', 'Stop all running jobs', 'job stop-all [--json]'),
    ), default='list', dispatch_subcommand=True, structured=True),
    command('history', 'Show Quick History or replay by index', children=(
        ('list', 'Display Quick History', 'history'),
        ('clear', 'Clear Quick Recent', 'history clear'),
        ('run', 'Replay a Quick command by index', 'history run <index>'),
    ), default='list'),
    command('gopin', 'Jump to saved path', expects_arguments=True),
    command('rtt', 'Show current heartbeat RTT'),
    command('httpctl', 'Client HTTP control channel', children=(
        ('kill', 'Terminate current Agent', 'httpctl kill'),
        ('relaunch', 'Relaunch Agent', 'httpctl relaunch'),
        ('clone', 'Clone Agent', 'httpctl clone'),
        ('resume', 'Resume original paused Client', 'httpctl resume [--client-id CLIENT_ID]'),
        ('help', 'Show HTTP control usage', 'httpctl help'),
    ), default='help'),
    command('saveout', 'Save Client command output as Artifact', expects_arguments=True),
    command('notify', 'Run a Client command and notify when finished', expects_arguments=True),
    command('xt', 'External tool catalog and execution', children=(
        ('exec', 'List or execute installed external tool commands', 'xt exec list|info|which|<exec-name> ...'),
        ('package', 'List, install or uninstall external tool packages', 'xt package list [--installed|-i] [--json] | install|uninstall <package-id>'),
        ('module', 'List package modules', 'xt module list <package-id> [--json]'),
        ('instance', 'Manage persistent daemon instances', 'xt instance create|list|start|stop|restart|status|logs ...'),
        ('help', 'Show external tool usage', 'xt help'),
    ), default='help'),
    command('help', 'Show Server builtin commands and subcommands', handler='server_help'),
)


@dataclass(frozen=True)
class BuiltinInvocation:
    command: str
    action: str
    arguments: dict
    output_format: OutputFormat



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
        raise ValueError(f'Unsupported {spec.name} subcommand: {token}. Use: {self.usage(spec.name)}')

    def parse_invocation(self, name, raw_arg, *, literal_backslashes=False):
        """Parse declared structured builtins once; other handlers stay RAW."""
        return self.parse_leaf(*self.parse(name, raw_arg),
                               literal_backslashes=literal_backslashes)

    def parse_leaf(self, spec, subcommand, tail, *, literal_backslashes=False):
        """Use the already resolved leaf: no second command-name parse."""
        child = spec.child(subcommand)
        schema = child.argument_spec if child is not None else None
        if schema is None:
            raise ValueError(f'No structured argument schema for: {spec.name} {subcommand}')
        try:
            args = parse_argument_text(schema, tail, literal_backslashes=literal_backslashes)
        except ArgumentCommandValidationError as exc:
            exc.output_format = (OutputFormat.JSON if 'json' in getattr(exc, 'seen_flags', ())
                                 else OutputFormat.TEXT)
            raise
        return BuiltinInvocation(spec.name, subcommand, args,
                                 OutputFormat.JSON if args.get('json') else OutputFormat.TEXT)

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
        return [dict(name=spec.name + (' ' if spec.subcommands or spec.expects_arguments else ''),
                     help=spec.description, source='server', group=spec.group,
                     suggest=spec.suggest,
                     subcommands=[dict(name=child.name, usage=child.usage,
                                       description=child.description)
                                  for child in spec.subcommands if child.visibility == 'public'])
                for spec in self._commands.values()]


SERVER_COMMAND_REGISTRY = ServerCommandRegistry()
