"""Single explicit source of Server builtin names, subcommands, help and completion.

Business implementations stay in their existing support classes.  The parser
preserves raw tails for alias templates, shell-like arguments and structured JSON.
Unknown commands are deliberately *not* claimed: they can reach the Client Shell.
"""
from dataclasses import dataclass
from core.commands.argument_errors import ArgumentCommandValidationError
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.commands.argument_parser import parse_argument_text
from core.commands.command_line_resolver import CommandLineResolver
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
    subcommands: tuple['SubcommandSpec', ...] = ()
    default: str = ''
    fallback_subcommand: str = ''

    def child(self, name):
        return next((item for item in self.subcommands if name == item.name or name in item.aliases), None)


@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    handler: str
    subcommands: tuple[SubcommandSpec, ...] = ()
    default: str = ''
    suggest: bool = True
    group: str = 'server'
    expects_arguments: bool = False
    argument_spec: ArgumentCommandSpec | None = None
    raw_tail: bool = False
    fallback_subcommand: str = ''
    independent: bool = False

    def child(self, name):
        return next((item for item in self.subcommands if name == item.name or name in item.aliases), None)


def command(name, description, handler=None, children=(), default='', group='server', expects_arguments=False, argument_spec=None, raw_tail=False, fallback_subcommand='', independent=False):
    return CommandSpec(name, description, handler or name,
                       tuple(item if isinstance(item, SubcommandSpec) else SubcommandSpec(*item)
                             for item in children),
                       default, True, group, expects_arguments,
                       argument_spec, raw_tail, fallback_subcommand, independent)



def _option(name, *, positional=None, required=False, flag=False, alias='', arity=1, repeatable=False, value_type='str'):
    return ArgumentOptionSpec(name=name, option_type='flag' if flag else value_type,
                              default=False if flag else ([] if repeatable else None),
                              required=required, positional_index=positional,
                              allow_empty=False, alias=alias, arity=arity,
                              repeatable=repeatable)


def _arguments(name, *options, json=True, trailing_named_arguments=None, assignment_tail=None):
    return ArgumentCommandSpec(
        name, options=[*options, *([_option('json', flag=True)] if json else [])],
        trailing_named_arguments=trailing_named_arguments, assignment_tail=assignment_tail)


def _structured_child(command_name, action, description, usage, *options,
                      json=True, trailing_named_arguments=None, assignment_tail=None, aliases=(), independent=False):
    return SubcommandSpec(action, description, usage, argument_spec=_arguments(
        f'{command_name} {action}', *options, json=json,
        trailing_named_arguments=trailing_named_arguments, assignment_tail=assignment_tail), aliases=tuple(aliases), independent=independent)

def _xt_group(name, description, *children, default='', fallback_subcommand=''):
    return SubcommandSpec(name, description, subcommands=tuple(children),
                          default=default, fallback_subcommand=fallback_subcommand)


def _xt_leaf(path, action, description, usage, *options, json=True,
             trailing_named_arguments=None, independent=False):
    return _structured_child(f'xt {path}', action, description, usage, *options,
                             json=json, trailing_named_arguments=trailing_named_arguments,
                             independent=independent)


def _xt_instance_target(action, description, *, json=False, follow=False, params=False):
    opts = [_option('name', positional=0), _option('instance', positional=1), _option('module')]
    if follow:
        opts.append(_option('follow', flag=True, alias='f'))
    return _xt_leaf('instance', action, description,
                    f'xt instance {action} [<module>] <instance-id>|--name ID [--module MODULE]'
                    + (' [--follow|-f]' if follow else '')
                    + (' [-- --key VALUE ...]' if params else '')
                    + (' [--json]' if json else ''),
                    *opts, json=json, trailing_named_arguments='params' if params else None,
                    independent=action in ('status', 'logs'))


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
    ), default='list', group='runtime'),
    command('watchdog', 'Show watchdog runtime status', expects_arguments=True, group='runtime',
             argument_spec=_arguments('watchdog'), independent=True),
    command('upload', 'Upload a local file to the Client', expects_arguments=True,
             raw_tail=True),
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
    ), default='list'),
    command('alias', 'List or manage aliases for this Client platform', children=(
        _structured_child('alias', 'list', 'List current effective aliases',
                          'alias [list] [--json]', independent=True),
        _structured_child('alias', 'set', 'Save an alias',
                          'alias set <name>|--name NAME [--platform PLATFORM|-p PLATFORM] = command',
                          _option('name', positional=0, required=True), _option('platform', alias='p'),
                          json=False, assignment_tail='definition'),
        _structured_child('alias', 'unset', 'Remove an alias',
                          'alias unset <name>|--name NAME [--platform PLATFORM|-p PLATFORM]',
                          _option('name', positional=0, required=True), _option('platform', alias='p'),
                          json=False),
    ), default='list'),
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
    ), default='list'),
    command('history', 'Show Quick History or replay by index', children=(
        _structured_child('history', 'list', 'Display Quick History', 'history [list] [-p|--pinned] [--json]',
                          _option('pinned', flag=True, alias='p'), independent=True),
        _structured_child('history', 'clear', 'Clear Quick Recent (keep pins)', 'history clear [--json]'),
        _structured_child('history', 'run', 'Replay a Quick command by index', 'history run <index>|--index INDEX',
                          _option('index', positional=0, required=True, value_type='int'), json=False),
    ), default='list'),
    command('gopin', 'List or jump to a saved path', children=(
        _structured_child('gopin', 'list', 'List saved paths', 'gopin [list] [--json]', independent=True),
        SubcommandSpec('go', 'Jump to a saved path', 'gopin [go] <saved path name>', raw_tail=True),
    ), default='list', fallback_subcommand='go', expects_arguments=True,
            ),
    command('rtt', 'Show current heartbeat RTT', argument_spec=_arguments('rtt'), independent=True),
    command('httpctl', 'Client HTTP control channel', children=(
        _structured_child('httpctl', 'kill', 'Terminate current Agent', 'httpctl kill [--json]'),
        _structured_child('httpctl', 'relaunch', 'Relaunch Agent', 'httpctl relaunch [--json]'),
        _structured_child('httpctl', 'clone', 'Clone Agent', 'httpctl clone [--json]'),
        _structured_child('httpctl', 'resume', 'Resume original paused Client',
                          'httpctl resume [--client-id CLIENT_ID] [--json]', _option('client-id')),
        _structured_child('httpctl', 'help', 'Show HTTP control usage', 'httpctl help [--json]',
                          aliases=('-h', '--help')),
    ), default='help'),
    command('saveout', 'Save Client command output as Artifact', expects_arguments=True,
             raw_tail=True),
    command('notify', 'Run a Client command and notify when finished', expects_arguments=True,
             raw_tail=True),
    command('xt', 'External tool catalog and execution', children=(
        _xt_group('exec', 'List or run installed external commands',
            _xt_leaf('exec', 'list', 'List installed exec commands', 'xt exec list [--json]', independent=True),
            _xt_leaf('exec', 'info', 'Read exec metadata', 'xt exec info <name>|--name NAME [--json]',
                     _option('name', positional=0, required=True), independent=True),
            _xt_leaf('exec', 'which', 'Locate an installed executable', 'xt exec which <name>|--name NAME',
                     _option('name', positional=0, required=True), json=False, independent=True),
            SubcommandSpec('run', 'Run an installed external command with native arguments',
                           'xt exec run <exec-name> [--] <native args...> (short: xt exec <exec-name> ...)', raw_tail=True),
            _xt_leaf('exec', 'help', 'Show exec command usage', 'xt exec help', json=False),
            default='help', fallback_subcommand='run'),
        _xt_group('package', 'Manage external tool packages',
            _xt_leaf('package', 'list', 'List available packages',
                     'xt package list [--installed|-i] [--json]',
                     _option('installed', flag=True, alias='i'), independent=True),
            _xt_leaf('package', 'install', 'Install a package',
                     'xt package install <package-id>|--package PACKAGE',
                     _option('package', positional=0, required=True), json=False),
            _xt_leaf('package', 'uninstall', 'Uninstall a package',
                     'xt package uninstall <package-id>|--package PACKAGE',
                     _option('package', positional=0, required=True), json=False)),
        _xt_group('module', 'Inspect external tool modules',
            _xt_leaf('module', 'list', 'List package modules',
                     'xt module list <package-id>|--package PACKAGE [--json]',
                     _option('package', positional=0, required=True), independent=True)),
        _xt_group('instance', 'Manage persistent daemon instances',
            _xt_leaf('instance', 'create', 'Create an instance',
                     'xt instance create <module>|--module MODULE --id ID [--preset PRESET] [--start] [-- --key VALUE ...]',
                     _option('module', positional=0, required=True), _option('id', required=True),
                     _option('preset'), _option('start', flag=True), json=False,
                     trailing_named_arguments='params'),
            _xt_leaf('instance', 'list', 'List persistent instances',
                     'xt instance list [<name>|--name NAME] [--json]',
                     _option('name', positional=0), independent=True),
            _xt_instance_target('start', 'Start an existing instance', params=True),
            _xt_instance_target('stop', 'Stop a running instance'),
            _xt_instance_target('restart', 'Restart an instance', params=True),
            _xt_instance_target('status', 'Show instance status', json=True),
            _xt_instance_target('logs', 'Read or follow instance logs', follow=True)),
        _xt_leaf('', 'help', 'Show external tool usage', 'xt help', json=False),
    ), default='help'),
    command('help', 'Show Server builtin commands and subcommands', handler='server_help',
             argument_spec=_arguments('help',
                _option('target', positional=0), _option('subcommand', positional=1),
                _option('action', positional=2), json=False), independent=True),
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
        self._resolver = CommandLineResolver()
        if len(self._commands) != len(definitions):
            raise ValueError('Duplicate server builtin command name')

    def get(self, name):
        return self._commands.get(str(name or '').lower())

    def parse(self, name, raw_arg):
        """Walk declared command paths before parsing arguments at the final leaf."""
        spec = self.get(name)
        if spec is None:
            return None
        if not spec.subcommands:
            # Non-hierarchical raw-tail commands must retain every byte,
            # including leading whitespace inside shell-like arguments.
            return spec, None, str(raw_arg or '')
        node = spec
        text = str(raw_arg or '').lstrip()
        offset = 0
        path = []
        while node.subcommands:
            remaining = text[offset:]
            tokens = self._resolver.scan_tokens(remaining, max_tokens=1)
            token = tokens[0] if tokens else None
            token_text = token.raw.lower() if token is not None else ''
            child = node.child(token_text) if token_text else None
            if child is not None:
                offset += token.end
                if offset < len(text) and text[offset].isspace():
                    offset += 1
            else:
                default = node.child(node.default) if node.default else None
                if not token_text and default is not None:
                    child = default
                elif token_text.startswith('-') and default is not None and default.argument_spec is not None:
                    child = default
                elif node.fallback_subcommand:
                    child = node.child(node.fallback_subcommand)
                if child is None:
                    prefix = ' '.join((spec.name, *path))
                    raise ValueError(f'Unsupported {prefix} subcommand: {token_text or "(none)"}. Use: {self.usage(spec.name)}')
                # Default/fallback leaves receive the unconsumed tail verbatim.
            path.append(child.name)
            node = child
        return spec, '.'.join(path) if path else None, text[offset:]

    def parse_invocation(self, name, raw_arg, *, literal_backslashes=False):
        return self.parse_leaf(*self.parse(name, raw_arg),
                               literal_backslashes=literal_backslashes)

    @staticmethod
    def _leaf(spec, action):
        node = spec
        for part in str(action or '').split('.') if action else ():
            node = node.child(part)
            if node is None:
                raise ValueError(f'Unknown command path: {spec.name} {action}')
        return node

    def parse_leaf(self, spec, subcommand, tail, *, literal_backslashes=False):
        """Parse the final leaf only, never dispatch XT-specific command strings."""
        leaf = self._leaf(spec, subcommand)
        if leaf.raw_tail:
            return BuiltinInvocation(spec.name, subcommand or spec.name,
                                     {'command': tail}, OutputFormat.TEXT)
        schema = leaf.argument_spec
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

    def _public_paths(self, node, prefix=()):
        for child in node.subcommands:
            if child.visibility != 'public':
                continue
            path = (*prefix, child.name)
            if child.subcommands:
                yield from self._public_paths(child, path)
            else:
                yield path, child

    def completion_paths(self, name):
        """The one source of static command completion, including nested leaves."""
        spec = self.get(name)
        if spec is None:
            return []
        def walk(node, prefix):
            for child in node.subcommands:
                if child.subcommands:
                    yield from walk(child, (*prefix, child.name))
                elif child.visibility == 'public' and child.name != 'help':
                    suffix = ' ' if (child.argument_spec and child.name != 'list' and any(
                            opt.is_positional for opt in child.argument_spec.options)) else ''
                    full = ' '.join((name, *prefix, child.name))
                    yield full + suffix, child.description
                    if child.name == 'list' and child.argument_spec:
                        for opt in child.argument_spec.options:
                            if opt.is_flag and opt.name != 'json':
                                yield f'{full} --{opt.name}', child.description
            if node.fallback_subcommand:
                leaf = node.child(node.fallback_subcommand)
                if leaf is not None:
                    yield ' '.join((name, *prefix)) + ' ', leaf.description
        return list(walk(spec, ()))

    def usage(self, name):
        spec = self.get(name)
        if spec is None:
            raise ValueError(f'Unknown Server command: {name}')
        if not spec.subcommands:
            return f'{spec.name} — {spec.description}'
        return '\n'.join([f'{spec.name} — {spec.description}'] +
                         [f'  {leaf.usage or " ".join((spec.name, *path))} — {leaf.description}'
                          for path, leaf in self._public_paths(spec)])

    def help(self, target=''):
        target = str(target or '').strip().lower()
        if not target:
            return '\n'.join(f'{spec.name:<13} {spec.description}' for spec in self._commands.values())
        words = target.split()
        spec = self.get(words[0])
        if spec is None:
            raise ValueError(f'Unknown Server command: {words[0]}')
        node = spec
        for word in words[1:]:
            node = node.child(word)
            if node is None or node.visibility != 'public':
                raise ValueError(f'Unknown subcommand: {target}')
        if node.subcommands:
            lines = [f'{target} — {node.description}']
            return '\n'.join(lines +
                [f'  {leaf.usage or " ".join((target, *path))} — {leaf.description}'
                 for path, leaf in self._public_paths(node)])
        return f'{node.usage} — {node.description}' if node is not spec else self.usage(spec.name)

    def is_independent_input(self, raw_command: str) -> bool:
        from core.utils.parsing import parse
        try:
            name, tail = parse(str(raw_command or '').strip())
            spec, action, _ = self.parse(name, tail)
            leaf = self._leaf(spec, action)
            return bool(leaf.independent)
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
