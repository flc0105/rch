"""Single explicit source of Server builtin names, subcommands, help and completion.

Business implementations stay in their existing support classes.  The parser
preserves raw tails for alias templates, shell-like arguments and structured JSON.
Unknown commands are deliberately *not* claimed: they can reach the Client Shell.
"""
from dataclasses import dataclass, field
from core.command_completion.models import CompletionSpec
from core.commands.argument_errors import ArgumentCommandValidationError
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.commands.argument_parser import parse_argument_text, parse_partial_argument_tokens
from core.commands.command_line_resolver import CommandLineResolver
from core.utils.command_output import OutputFormat, resolve_presentation


@dataclass(frozen=True)
class ServerCompletionTarget:
    """Resolved parameter at the cursor; not part of the wire CompletionSpec."""
    completion: CompletionSpec
    path: tuple[str, ...]
    argument: str
    prefix: str
    tokens: tuple[str, ...]
    arguments: dict = field(default_factory=dict)
    named_options: frozenset[str] = frozenset()


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
    completion: CompletionSpec | None = None

    def child(self, name):
        return next((item for item in self.subcommands if name == item.name or name in item.aliases), None)


@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    handler: str
    subcommands: tuple[SubcommandSpec, ...] = ()
    default: str = ''
    group: str = 'server'
    expects_arguments: bool = False
    argument_spec: ArgumentCommandSpec | None = None
    raw_tail: bool = False
    fallback_subcommand: str = ''
    independent: bool = False
    completion: CompletionSpec | None = None

    def child(self, name):
        return next((item for item in self.subcommands if name == item.name or name in item.aliases), None)


def command(name, description, handler=None, children=(), default='', group='server', expects_arguments=False, argument_spec=None, raw_tail=False, fallback_subcommand='', independent=False, completion=None):
    return CommandSpec(name, description, handler or name,
                       tuple(item if isinstance(item, SubcommandSpec) else SubcommandSpec(*item)
                             for item in children),
                       default, group, expects_arguments,
                       argument_spec, raw_tail, fallback_subcommand, independent, completion)



def _option(name, *, positional=None, required=False, flag=False, alias='', arity=1, repeatable=False, value_type='str', completion=None, choices=None):
    return ArgumentOptionSpec(name=name, option_type='flag' if flag else value_type,
                              default=False if flag else ([] if repeatable else None),
                              required=required, positional_index=positional,
                              allow_empty=False, alias=alias, arity=arity,
                              repeatable=repeatable, completion=completion, choices=choices)


def _arguments(name, *options, json=True, trailing_named_arguments=None, assignment_tail=None):
    return ArgumentCommandSpec(
        name, options=[*options, *([_option('json', flag=True)] if json else [])],
        trailing_named_arguments=trailing_named_arguments, assignment_tail=assignment_tail)


def _structured_child(command_name, action, description, usage, *options,
                      json=True, trailing_named_arguments=None, assignment_tail=None, aliases=(), independent=False, completion=None):
    return SubcommandSpec(action, description, usage, argument_spec=_arguments(
        f'{command_name} {action}', *options, json=json,
        trailing_named_arguments=trailing_named_arguments, assignment_tail=assignment_tail), aliases=tuple(aliases), independent=independent, completion=completion)

def _format_options(*layouts):
    # The owning command declares permitted layouts once in its argument Spec.
    return (_option('format', alias='f', choices=(*layouts, 'json')),)


def _xt_group(name, description, *children, default='', fallback_subcommand=''):
    return SubcommandSpec(name, description, subcommands=tuple(children),
                          default=default, fallback_subcommand=fallback_subcommand)


def _xt_leaf(path, action, description, usage, *options, json=True,
             trailing_named_arguments=None, independent=False, completion=None):
    return _structured_child(f'xt {path}', action, description, usage, *options,
                             json=json, trailing_named_arguments=trailing_named_arguments,
                             independent=independent, completion=completion)


def _xt_instance_target(action, description, *, json=False, follow=False, params=False):
    opts = [_option('name', positional=0, completion=CompletionSpec('xt', ('instance',))),
            _option('instance', positional=1, completion=CompletionSpec('xt', ('instance',))),
            _option('module', completion=CompletionSpec('xt', ('module',)))]
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
        _structured_child('config', 'list', 'List runtime config', 'config [list] [--format|-f LAYOUT] [--json]', *_format_options('grouped', 'kv', 'table', 'records'), independent=True),
        _structured_child('config', 'set', 'Set one runtime config value',
                          'config set <key> <value> [--json]',
                          _option('key', positional=0, required=True, completion=CompletionSpec('configuration', ('key',))),
                          _option('value', positional=1, required=True)),
        _structured_child('config', 'reset', 'Reset one runtime config value',
                          'config reset <key> [--json]', _option('key', positional=0, required=True, completion=CompletionSpec('configuration', ('key',)))),
        _structured_child('config', 'reset-all', 'Reset all config overrides', 'config reset-all [--json]'),
    ), default='list', group='runtime'),
    command('watchdog', 'Show watchdog runtime status', expects_arguments=True, group='runtime',
             argument_spec=_arguments('watchdog', *_format_options('grouped')), independent=True),
    command('upload', 'Upload a local file to the Client', expects_arguments=True,
             raw_tail=True, completion=CompletionSpec('filesystem', ('file', 'directory'))),
    command('script', 'List, inspect and run Server scripts', children=(
        _structured_child('script', 'list', 'List available scripts',
                          'script [list] [--format|-f LAYOUT] [--json]',
                          *_format_options('lines', 'table', 'records'), independent=True),
        _structured_child('script', 'view', 'Read script source on the Server',
                          'script view <name>|--name NAME',
                          _option('name', positional=0, required=True, completion=CompletionSpec('scripts', ('script',))), json=False, independent=True),
        _structured_child('script', 'exec', 'Execute a script with CLI arguments',
                          'script exec <name>|--name NAME [--execution_mode MODE] [--output_mode MODE] [-- --key VALUE]...',
                          _option('name', positional=0, required=True, completion=CompletionSpec('scripts', ('script',))),
                          _option('execution_mode'), _option('output_mode'),
                          json=False, trailing_named_arguments='params'),
    ), default='list'),
    command('alias', 'List or manage aliases for this Client platform', children=(
        _structured_child('alias', 'list', 'List current effective aliases',
                          'alias [list] [--format|-f LAYOUT] [--json]',
                          *_format_options('lines', 'kv', 'table', 'records', 'grouped'), independent=True),
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
        _structured_child('job', 'list', 'List available Server jobs',
                          'job [list] [--format|-f LAYOUT] [--json]',
                          *_format_options('lines', 'table', 'records'), independent=True),
        _structured_child('job', 'start', 'Start a Client job',
                          'job start <name>|--name NAME [--mode MODE] [--json] [-- --key VALUE]...',
                          _option('name', positional=0, required=True, completion=CompletionSpec('jobs', ('job',))), _option('mode'),
                          trailing_named_arguments='params'),
        _structured_child('job', 'logs', 'Read stored Job reports or follow new reports',
                          'job logs <name> [--follow|-f]',
                          _option('name', positional=0, required=True, completion=CompletionSpec('jobs', ('job',))),
                          _option('follow', flag=True, alias='f'), json=False),
        _structured_child('job', 'ps', 'Show running jobs', 'job ps [--format|-f LAYOUT] [--json]', *_format_options('table', 'records'), independent=True),
        _structured_child('job', 'status', 'Query job state', 'job status <name> [--format|-f LAYOUT] [--json]',
                          _option('name', positional=0, required=True, completion=CompletionSpec('jobs', ('job',))), *_format_options('flat', 'kv'), independent=True),
        _structured_child('job', 'stop', 'Stop a running job', 'job stop <name> [--json]',
                          _option('name', positional=0, required=True, completion=CompletionSpec('jobs', ('job',)))),
        _structured_child('job', 'stop-all', 'Stop all running jobs', 'job stop-all [--json]'),
    ), default='list'),
    command('history', 'Show Quick History or replay by index', children=(
        _structured_child('history', 'list', 'Display Quick History', 'history [list] [-p|--pinned] [--format|-f LAYOUT] [--json]',
                          _option('pinned', flag=True, alias='p'), *_format_options('numbered', 'table', 'records'), independent=True),
        _structured_child('history', 'clear', 'Clear Quick Recent (keep pins)', 'history clear [--json]'),
        _structured_child('history', 'run', 'Replay a Quick command by index', 'history run <index>|--index INDEX',
                          _option('index', positional=0, required=True, value_type='int'), json=False),
    ), default='list'),
    command('gopin', 'List or jump to a saved path', children=(
        _structured_child('gopin', 'list', 'List saved paths', 'gopin [list] [--format|-f LAYOUT] [--json]', *_format_options('table', 'records'), independent=True),
        SubcommandSpec('go', 'Jump to a saved path', 'gopin [go] <saved path name>', raw_tail=True,
                       completion=CompletionSpec('gopin', ('quick_jump',))),
    ), default='list', fallback_subcommand='go', expects_arguments=True,
            ),
    command('rtt', 'Show current heartbeat RTT', argument_spec=_arguments('rtt', *_format_options('flat', 'kv')), independent=True),
    command('tunnel', 'Manage saved TCP tunnel instances', children=(
        _structured_child('tunnel', 'create', 'Save a tunnel without starting',
                          'tunnel create --name NAME --listen-port PORT --target-port PORT [--listen-host HOST] [--target-host HOST] [--expose-on client|server]',
                          _option('name', required=True), _option('expose_on'), _option('listen_host'),
                          _option('listen_port', required=True, value_type='int'),
                          _option('target_host'), _option('target_port', required=True, value_type='int'),
                          json=False),
        _structured_child('tunnel', 'start', 'Start a saved instance or create and start',
                          'tunnel start --name NAME [--listen-port PORT --target-port PORT] [--listen-host HOST] [--target-host HOST] [--expose-on client|server]',
                          _option('name', required=True), _option('expose_on'), _option('listen_host'),
                          _option('listen_port', value_type='int'),
                          _option('target_host'), _option('target_port', value_type='int'),
                          json=False),
        _structured_child('tunnel', 'list', 'List saved tunnel instances', 'tunnel [list] [--json]', independent=True),
        _structured_child('tunnel', 'status', 'Inspect tunnel status', 'tunnel status [--name NAME] [--json]',
                          _option('name'), independent=True),
        _structured_child('tunnel', 'stop', 'Stop one or all running instances',
                          'tunnel stop --name NAME|--all', _option('name'), _option('all', flag=True), json=False),
        _structured_child('tunnel', 'restart', 'Restart a saved tunnel instance',
                          'tunnel restart --name NAME', _option('name', required=True), json=False),
        _structured_child('tunnel', 'edit', 'Edit a stopped tunnel instance',
                          'tunnel edit --name NAME [--listen-host HOST] [--listen-port PORT] [--target-host HOST] [--target-port PORT] [--expose-on client|server]',
                          _option('name', required=True), _option('expose_on'), _option('listen_host'),
                          _option('listen_port', value_type='int'), _option('target_host'),
                          _option('target_port', value_type='int'), json=False),
        _structured_child('tunnel', 'remove', 'Delete a stopped tunnel instance',
                          'tunnel remove --name NAME', _option('name', required=True), json=False),
    ), default='list'),
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
            _xt_leaf('exec', 'list', 'List installed exec commands', 'xt exec list [--format|-f LAYOUT] [--json]', *_format_options('lines', 'table', 'records'), independent=True),
            _xt_leaf('exec', 'info', 'Read exec metadata', 'xt exec info <name>|--name NAME [--format|-f LAYOUT] [--json]',
                     _option('name', positional=0, required=True, completion=CompletionSpec('xt', ('exec',))), *_format_options('flat', 'kv'), independent=True),
            _xt_leaf('exec', 'which', 'Locate an installed executable', 'xt exec which <name>|--name NAME',
                     _option('name', positional=0, required=True, completion=CompletionSpec('xt', ('exec',))), json=False, independent=True),
            SubcommandSpec('run', 'Run an installed external command with native arguments',
                           'xt exec run <exec-name> [--] <native args...> (short: xt exec <exec-name> ...)',
                           raw_tail=True, completion=CompletionSpec('xt', ('exec',))),
            _xt_leaf('exec', 'help', 'Show exec command usage', 'xt exec help', json=False),
            default='help', fallback_subcommand='run'),
        _xt_group('package', 'Manage external tool packages',
            _xt_leaf('package', 'list', 'List available packages',
                     'xt package list [--installed|-i] [--format|-f LAYOUT] [--json]',
                     _option('installed', flag=True, alias='i'), *_format_options('lines', 'table', 'records'), independent=True),
            _xt_leaf('package', 'install', 'Install a package',
                     'xt package install <package-id>|--package PACKAGE',
                     _option('package', positional=0, required=True, completion=CompletionSpec('xt', ('package',))), json=False),
            _xt_leaf('package', 'uninstall', 'Uninstall a package',
                     'xt package uninstall <package-id>|--package PACKAGE',
                     _option('package', positional=0, required=True, completion=CompletionSpec('xt', ('package',))), json=False)),
        _xt_group('module', 'Inspect external tool modules',
            _xt_leaf('module', 'list', 'List package modules',
                     'xt module list <package-id>|--package PACKAGE [--format|-f LAYOUT] [--json]',
                     _option('package', positional=0, required=True, completion=CompletionSpec('xt', ('package',))), *_format_options('lines', 'table', 'records'), independent=True)),
        _xt_group('instance', 'Manage persistent daemon instances',
            _xt_leaf('instance', 'create', 'Create an instance',
                     'xt instance create <module>|--module MODULE --id ID [--preset PRESET] [--start] [-- --key VALUE ...]',
                     _option('module', positional=0, required=True, completion=CompletionSpec('xt', ('module',))), _option('id', required=True),
                     _option('preset'), _option('start', flag=True), json=False,
                     trailing_named_arguments='params'),
            _xt_leaf('instance', 'list', 'List persistent instances',
                     'xt instance list [<name>|--name NAME] [--format|-f LAYOUT] [--json]',
                     _option('name', positional=0, completion=CompletionSpec('xt', ('package',))), *_format_options('lines', 'table', 'records'), independent=True),
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
        # All declared --format flags are interpreted at this one registry boundary.
        # Per-command permitted layouts are checked by the shared option validator.
        output, _ = resolve_presentation(args)
        return BuiltinInvocation(spec.name, subcommand or spec.name, args, output)

    def resolve_completion_target(self, context):
        """Find a registered dynamic argument without executing or validating a command."""
        source = context.raw_input or f'{context.command_name} {context.argument_text}'
        cursor = context.cursor_position if context.raw_input else len(source)
        source = source[:cursor]
        tokens = self._resolver.scan_tokens(source)
        if not tokens:
            return None
        node = self.get(tokens[0].value.lower())
        if node is None:
            return None
        path = [node.name]
        index = 1
        while node.subcommands:
            child = node.child(tokens[index].value.lower()) if index < len(tokens) else None
            if child is not None:
                path.append(child.name)
                node = child
                index += 1
                continue
            fallback = node.child(node.fallback_subcommand) if node.fallback_subcommand else None
            if fallback is None:
                return None
            path.append(fallback.name)
            node = fallback
        # `--` belongs to the executed command's native parameter tail.
        values = tuple(token.value for token in tokens[index:])
        if '--' in values:
            return None
        arguments, named_options = {}, frozenset()
        if node.argument_spec is not None:
            try:
                arguments, named_options = parse_partial_argument_tokens(
                    node.argument_spec, values)
            except ArgumentCommandValidationError:
                return None
            resolved = self._resolver.resolve_completion_argument(
                source, len(source), tokens, node.argument_spec, command_token_count=index)
            if resolved is not None:
                completion, span = resolved
                option = next((item for item in node.argument_spec.options
                               if item.completion is completion), None)
                if option is not None:
                    return ServerCompletionTarget(completion, tuple(path), option.name,
                                                  source[:span[0]], values, arguments, named_options)
        if node.completion is None:
            return None
        # Complex targets and raw tails use their owning node's declaration.
        if node.raw_tail and len(values) > 1:
            return None
        return ServerCompletionTarget(node.completion, tuple(path), '',
                                      source[:tokens[index].start] if index < len(tokens)
                                      else source + ('' if source.endswith(' ') else ' '), values,
                                      arguments, named_options)

    def _iter_public_nodes(self, node, prefix=()):
        """Walk public command nodes once, including nested groups and leaves."""
        for child in node.subcommands:
            if child.visibility != 'public':
                continue
            path = (*prefix, child.name)
            yield path, child
            yield from self._iter_public_nodes(child, path)

    def iter_public_nodes(self, name):
        spec = self.get(name)
        return self._iter_public_nodes(spec) if spec else iter(())

    def _public_paths(self, node, prefix=()):
        return ((path, child) for path, child in self._iter_public_nodes(node, prefix)
                if not child.subcommands)

    def child_names(self, command_path):
        parts = str(command_path or '').strip().split()
        node = self.get(parts[0]) if parts else None
        for part in parts[1:]:
            node = node.child(part) if node else None
        return tuple(child.name for child in node.subcommands if child.visibility == 'public') if node else ()

    def static_completion_candidates(self, name):
        """Return complete insertion values and their declaring Registry nodes."""
        spec = self.get(name)
        if spec is None:
            return []
        result = []
        for path, node in self.iter_public_nodes(name):
            full = ' '.join((name, *path))
            takes_value = (node.raw_tail or bool(node.completion)
                           or bool(node.argument_spec and any(
                               option.is_positional for option in node.argument_spec.options)))
            result.append((full + (' ' if node.subcommands or takes_value else ''), node))
            if node.name == 'list' and node.argument_spec:
                for option in node.argument_spec.options:
                    if option.name == 'format':
                        result.append((f'{full} --format ', node))
                    elif option.is_flag and option.name != 'json':
                        result.append((f'{full} --{option.name}', node))
        if spec.fallback_subcommand:
            leaf = spec.child(spec.fallback_subcommand)
            if leaf:
                result.append((name + ' ', leaf))
        return result

    def completion_paths(self, name):
        """Public leaf insertions, used by command/help catalogs."""
        return [(text, node.description) for text, node in self.static_completion_candidates(name)
                if not node.subcommands or node.fallback_subcommand or text == name + ' ']

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
                     subcommands=[dict(name=child.name, usage=child.usage,
                                       description=child.description)
                                  for child in spec.subcommands if child.visibility == 'public'])
                for spec in self._commands.values()]


SERVER_COMMAND_REGISTRY = ServerCommandRegistry()
