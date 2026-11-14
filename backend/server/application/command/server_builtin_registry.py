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
    aliases: tuple[str, ...] = ()
    raw_tail: bool = False
    independent: bool = False


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
    argument_spec: ArgumentCommandSpec | None = None
    raw_tail: bool = False
    fallback_subcommand: str = ''
    independent: bool = False

    def child(self, name):
        return next((item for item in self.subcommands if name == item.name or name in item.aliases), None)


def command(name, description, handler=None, children=(), default='', dispatch_subcommand=False, group='server', expects_arguments=False, structured=False, argument_spec=None, raw_tail=False, fallback_subcommand='', independent=False):
    return CommandSpec(name, description, handler or name,
                       tuple(item if isinstance(item, SubcommandSpec) else SubcommandSpec(*item)
                             for item in children),
                       default, dispatch_subcommand, True, group, expects_arguments, structured,
                       argument_spec, raw_tail, fallback_subcommand, independent)



def _option(name, *, positional=None, required=False, flag=False, alias='', arity=1, repeatable=False, value_type='str'):
    return ArgumentOptionSpec(name=name, option_type='flag' if flag else value_type,
                              default=False if flag else ([] if repeatable else None),
                              required=required, positional_index=positional,
                              allow_empty=False, alias=alias, arity=arity,
                              repeatable=repeatable)


def _arguments(name, *options, json=True, trailing_named_arguments=None):
    return ArgumentCommandSpec(
        name, options=[*options, *([_option('json', flag=True)] if json else [])],
        trailing_named_arguments=trailing_named_arguments)


def _structured_child(command_name, action, description, usage, *options,
                      json=True, trailing_named_arguments=None, aliases=(), independent=False):
    return SubcommandSpec(action, description, usage, argument_spec=_arguments(
        f'{command_name} {action}', *options, json=json,
        trailing_named_arguments=trailing_named_arguments), aliases=tuple(aliases), independent=independent)

SERVER_COMMAND_SPECS = (
    command('config', 'Show or update client runtime config', children=(
        _structured_child('config', 'list', 'List runtime config', 'config [list] [--json]', independent=True),
        _structured_child('config', 'set', 'Set one runtime config value',
                          'config set <key> <value> [--json]',
                          _option('key', positional=0, required=True),
                          _option('value', positional=1, required=True)),
        _structured_child('config', 'reset', 'Reset one runtime config value',
                          'config reset <key> [--json]', _option('key', positional=0, required=True)),
        _structured_child('config', 'reset-all', 'Reset all config overrides', 'config reset-all [--json]'),
    ), default='list', dispatch_subcommand=True, group='runtime', structured=True),
    command('watchdog', 'Show watchdog runtime status', expects_arguments=True, group='runtime',
            structured=True, argument_spec=_arguments('watchdog'), independent=True),
    command('upload', 'Upload a local file to the Client', expects_arguments=True,
            structured=True, raw_tail=True),
    command('script', 'List, inspect and run Server scripts', children=(
        _structured_child('script', 'list', 'List available scripts', 'script list [--json]', independent=True),
        _structured_child('script', 'view', 'Read script source on the Server',
                          'script view <name>|--name NAME',
                          _option('name', positional=0, required=True), json=False, independent=True),
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
        _structured_child('job', 'list', 'List available Server jobs', 'job list [--json]', independent=True),
        _structured_child('job', 'start', 'Start a Client job',
                          'job start <name>|--name NAME [--mode MODE] [--json] [-- --key VALUE]...',
                          _option('name', positional=0, required=True), _option('mode'),
                          trailing_named_arguments='params'),
        _structured_child('job', 'logs', 'Read stored Job reports or follow new reports',
                          'job logs <name> [--follow|-f]',
                          _option('name', positional=0, required=True),
                          _option('follow', flag=True, alias='f'), json=False),
        _structured_child('job', 'ps', 'Show running jobs', 'job ps [--json]', independent=True),
        _structured_child('job', 'status', 'Query job state', 'job status <name> [--json]',
                          _option('name', positional=0, required=True), independent=True),
        _structured_child('job', 'stop', 'Stop a running job', 'job stop <name> [--json]',
                          _option('name', positional=0, required=True)),
        _structured_child('job', 'stop-all', 'Stop all running jobs', 'job stop-all [--json]'),
    ), default='list', dispatch_subcommand=True, structured=True),
    command('history', 'Show Quick History or replay by index', children=(
        _structured_child('history', 'list', 'Display Quick History', 'history [list] [-p|--pinned] [--json]',
                          _option('pinned', flag=True, alias='p'), independent=True),
        _structured_child('history', 'clear', 'Clear Quick Recent (keep pins)', 'history clear [--json]'),
        _structured_child('history', 'run', 'Replay a Quick command by index', 'history run <index>|--index INDEX',
                          _option('index', positional=0, required=True, value_type='int'), json=False),
    ), default='list', dispatch_subcommand=True, structured=True),
    command('gopin', 'List or jump to a saved path', children=(
        _structured_child('gopin', 'list', 'List saved paths', 'gopin [list] [--json]', independent=True),
        SubcommandSpec('go', 'Jump to a saved path', 'gopin [go] <saved path name>', raw_tail=True),
    ), default='list', fallback_subcommand='go', expects_arguments=True,
            structured=True),
    command('rtt', 'Show current heartbeat RTT', structured=True, argument_spec=_arguments('rtt'), independent=True),
    command('httpctl', 'Client HTTP control channel', children=(
        _structured_child('httpctl', 'kill', 'Terminate current Agent', 'httpctl kill [--json]'),
        _structured_child('httpctl', 'relaunch', 'Relaunch Agent', 'httpctl relaunch [--json]'),
        _structured_child('httpctl', 'clone', 'Clone Agent', 'httpctl clone [--json]'),
        _structured_child('httpctl', 'resume', 'Resume original paused Client',
                          'httpctl resume [--client-id CLIENT_ID] [--json]', _option('client-id')),
        _structured_child('httpctl', 'help', 'Show HTTP control usage', 'httpctl help [--json]',
                          aliases=('-h', '--help')),
    ), default='help', structured=True),
    command('saveout', 'Save Client command output as Artifact', expects_arguments=True,
            structured=True, raw_tail=True),
    command('notify', 'Run a Client command and notify when finished', expects_arguments=True,
            structured=True, raw_tail=True),
    command('xt', 'External tool catalog and execution', children=(
        ('exec', 'List or execute installed external tool commands', 'xt exec list|info|which|<exec-name> ...'),
        ('package', 'List, install or uninstall external tool packages', 'xt package list [--installed|-i] [--json] | install|uninstall <package-id>'),
        ('module', 'List package modules', 'xt module list <package-id> [--json]'),
        ('instance', 'Manage persistent daemon instances', 'xt instance create|list|start|stop|restart|status|logs ...'),
        ('help', 'Show external tool usage', 'xt help'),
    ), default='help'),
    command('help', 'Show Server builtin commands and subcommands', handler='server_help',
            structured=True, argument_spec=_arguments('help',
                _option('target', positional=0), _option('subcommand', positional=1), json=False), independent=True),
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
        child = spec.child(token)
        if child is not None:
            return spec, child.name, tail
        # Registered default leaves accept their own options without `list`.
        default_child = spec.child(spec.default) if spec.default else None
        if token.startswith('-') and default_child and default_child.argument_spec is not None:
            return spec, spec.default, text
        if spec.fallback_subcommand:
            return spec, spec.fallback_subcommand, text
        raise ValueError(f'Unsupported {spec.name} subcommand: {token}. Use: {self.usage(spec.name)}')

    def parse_invocation(self, name, raw_arg, *, literal_backslashes=False):
        """Parse declared structured builtins once; other handlers stay RAW."""
        return self.parse_leaf(*self.parse(name, raw_arg),
                               literal_backslashes=literal_backslashes)

    def parse_leaf(self, spec, subcommand, tail, *, literal_backslashes=False):
        """Use the already resolved leaf: no second command-name parse."""
        child = spec.child(subcommand)
        if spec.raw_tail or (child is not None and child.raw_tail):
            # A declared raw-tail leaf owns every byte of its payload.
            return BuiltinInvocation(spec.name, subcommand or spec.name,
                                     {'command': tail}, OutputFormat.TEXT)
        schema = child.argument_spec if child is not None else spec.argument_spec
        if schema is None:
            raise ValueError(f'No structured argument schema for: {spec.name} {subcommand}')
        try:
            args = parse_argument_text(schema, tail, literal_backslashes=literal_backslashes)
        except ArgumentCommandValidationError as exc:
            exc.output_format = (OutputFormat.JSON if 'json' in getattr(exc, 'seen_flags', ())
                                 else OutputFormat.TEXT)
            raise
        return BuiltinInvocation(spec.name, subcommand or spec.name, args,
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

    def is_independent_input(self, raw_command: str) -> bool:
        from core.utils.parsing import parse
        try:
            name, tail = parse(str(raw_command or '').strip())
            spec, action, _ = self.parse(name, tail)
            if not spec.structured:
                return False
            child = spec.child(action) if action else None
            return bool(child.independent if child else spec.independent)
        except (ValueError, TypeError, AttributeError):
            return False

    def candidates(self):
        return [dict(name=spec.name + (' ' if spec.subcommands or spec.expects_arguments else ''),
                     help=spec.description, source='server', group=spec.group,
                     suggest=spec.suggest,
                     subcommands=[dict(name=child.name, usage=child.usage,
                                       description=child.description)
                                  for child in spec.subcommands if child.visibility == 'public'])
                for spec in self._commands.values()]


SERVER_COMMAND_REGISTRY = ServerCommandRegistry()
