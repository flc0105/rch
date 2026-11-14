import glob
import os
import re

from core.protocol.structured_arg_codec import encode_structured_arg
from core.command_completion.models import CompletionCandidate, CompletionContext
from core.platform.normalization import normalize_platform_alias
from core.platform.catalog_visibility import visible_on_platform
from core.utils.script_metadata import read_script_metadata_from_file
from core.command_completion.provider import CommandCompletionProvider
from server.application.history.quick_history import QuickHistoryRecordPolicy
from server.config.config import SCRIPT_PATH
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY


class ServerCompletionSessionMixin:
    """
    server completion provider 共用 session / machine 解析逻辑。
    """

    def __init__(self, server):
        self.server = server

    def get_client_id(self, context: CompletionContext) -> str:
        return str((context.metadata or {}).get('client_id') or '').strip()

    def get_session(self, context: CompletionContext):
        client_id = self.get_client_id(context)
        if not client_id:
            return None
        try:
            return self.server.get_target_connection_by_client_id(client_id)
        except Exception:
            return None

    def get_machine_id(self, context: CompletionContext) -> str:
        session = self.get_session(context)
        session_info = getattr(session, 'session_info', None)
        return getattr(session_info, 'machine_id', '') or 'unknown_machine'

    def get_client_platform(self, context: CompletionContext) -> str:
        session = self.get_session(context)
        session_info = getattr(session, 'session_info', None)
        return self._normalize_platform_alias(getattr(session_info, 'os_alias', '') if session_info is not None else '')

    def get_client_arch(self, context: CompletionContext) -> str:
        session = self.get_session(context)
        session_info = getattr(session, 'session_info', None)
        return str(getattr(session_info, 'arch', '') if session_info is not None else '').strip()

    def _normalize_platform_alias(self, value) -> str:
        return normalize_platform_alias(value, infer=True)


class GopinCommandCompletionProvider(ServerCompletionSessionMixin, CommandCompletionProvider):
    """
    server gopin 命令 quick jump 补全。
    """

    command_names = ('gopin',)
    source = 'server_gopin'
    group = 'quick_jump'

    def __init__(self, server, pinned_path_store):
        ServerCompletionSessionMixin.__init__(self, server)
        self.pinned_path_store = pinned_path_store

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        machine_id = self.get_machine_id(context)
        items = self.pinned_path_store.list_items(machine_id)

        result = []
        for item in items:
            display_name = str(item.get('display_name') or '').strip()
            target_path = str(item.get('path') or '').strip()
            if not display_name or not target_path:
                continue

            insert_text = f'gopin {display_name}'
            result.append(CompletionCandidate(
                title=insert_text,
                insert_text=insert_text,
                description=f'Quick jump -> {target_path}',
                source=self.source,
                group=self.group,
                kind='quick_jump',
                name=display_name,
                priority=10,
                metadata={
                    'path': target_path,
                    'displayName': display_name,
                },
            ))

        return result


class HistoryCommandCompletionProvider(ServerCompletionSessionMixin, CommandCompletionProvider):
    """
    server history run / !<index> 补全。
    """

    command_names = ('history',)
    source = 'server_history'
    group = 'history'
    shortcut_pattern = re.compile(r'^!\d*$', re.IGNORECASE)

    def __init__(self, server, command_history):
        ServerCompletionSessionMixin.__init__(self, server)
        self.command_history = command_history

    def supports(self, context: CompletionContext) -> bool:
        command_name = str(context.command_name or '').strip().lower()
        return command_name == 'history' or bool(self.shortcut_pattern.match(command_name))

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        command_name = str(context.command_name or '').strip().lower()
        entries = self._get_resolvable_quick_history(context)

        if self.shortcut_pattern.match(command_name):
            return self._build_shortcut_candidates(entries)

        items = [
            CompletionCandidate(
                title='history',
                insert_text='history',
                description='Show command history for current host',
                source=self.source,
                group=self.group,
                kind='history',
                name='history',
                priority=20,
            ),
            CompletionCandidate(
                title='history list --pinned',
                insert_text='history list --pinned',
                description='Show pinned Quick History only',
                source=self.source, group=self.group, kind='history',
                name='list', priority=21,
            ),
            CompletionCandidate(
                title='history clear',
                insert_text='history clear',
                description='Clear command history for current host',
                source=self.source,
                group=self.group,
                kind='history',
                name='clear',
                priority=21,
            ),
        ]
        items.extend(self._build_history_run_candidates(entries))
        return items

    def _get_resolvable_quick_history(self, context: CompletionContext) -> list[dict]:
        session = self.get_session(context)
        if session is None:
            return []

        entries = self.command_history.get_history_for_connection(session) or []
        result = []
        for item in entries:
            command_text = str(item.get('command') or '').strip()
            if not command_text:
                continue
            if QuickHistoryRecordPolicy.is_history_replay_command(command_text):
                continue

            cloned = dict(item)
            cloned['index'] = len(result) + 1
            result.append(cloned)
        return result

    def _build_history_run_candidates(self, entries: list[dict]) -> list[CompletionCandidate]:
        result = []
        for item in entries:
            index_value = int(item.get('index') or 0)
            command_text = str(item.get('command') or '').strip()
            if index_value <= 0 or not command_text:
                continue

            insert_text = f'history run {index_value}'
            result.append(CompletionCandidate(
                title=insert_text,
                insert_text=insert_text,
                description=command_text,
                source=self.source,
                group=self.group,
                kind='history_run',
                name=str(index_value),
                priority=30 + index_value,
                metadata={
                    'historyIndex': index_value,
                    'historyCommand': command_text,
                },
            ))
        return result

    def _build_shortcut_candidates(self, entries: list[dict]) -> list[CompletionCandidate]:
        result = []
        for item in entries:
            index_value = int(item.get('index') or 0)
            command_text = str(item.get('command') or '').strip()
            if index_value <= 0 or not command_text:
                continue

            insert_text = f'!{index_value}'
            result.append(CompletionCandidate(
                title=insert_text,
                insert_text=insert_text,
                description=command_text,
                source='quick_history_shortcut',
                group='quick_history',
                kind='history_shortcut',
                name=insert_text,
                priority=index_value,
                metadata={
                    'quickHistoryIndex': index_value,
                    'quickHistoryCommand': command_text,
                },
            ))
        return result


class RegisteredServerSubcommandCompletionProvider(CommandCompletionProvider):
    """Static subcommand autocomplete comes directly from executable registry."""
    command_names = tuple(spec.name for spec in SERVER_COMMAND_REGISTRY._commands.values()
                          if spec.subcommands)
    source = 'server'
    group = 'server'

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        spec = SERVER_COMMAND_REGISTRY.get(context.command_name)
        if not spec or not spec.subcommands:
            return []
        return [CompletionCandidate(
            title=f'{spec.name} {sub.name}',
            insert_text=f'{spec.name} {sub.name}' + (' ' if sub.name in
                {'exec', 'run', 'view', 'start', 'status', 'stop', 'set', 'unset', 'info', 'which'} else ''),
            description=sub.description,
            source=self.source, group=spec.group, kind='server_subcommand',
            name=sub.name, priority=18 + i,
        ) for i, sub in enumerate(spec.subcommands) if sub.visibility == 'public']


class ScriptCommandCompletionProvider(ServerCompletionSessionMixin, CommandCompletionProvider):
    """
    server script exec 脚本补全。
    """

    command_names = ('script',)
    source = 'script'
    group = 'script'

    def __init__(self, server, script_root: str = SCRIPT_PATH):
        ServerCompletionSessionMixin.__init__(self, server)
        self.script_root = script_root

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        tokens = str(context.argument_text or '').strip().split()
        if not tokens or tokens[0].lower() not in ('view', 'exec'):
            return []
        action = tokens[0].lower()
        # Suggest script names at the name slot, whether positional or --name.
        if len(tokens) > 1 and tokens[1].startswith('--') and tokens[1] != '--name':
            return []
        if len(tokens) > 2 and tokens[1] != '--name':
            return []
        if len(tokens) > 3:
            return []
        prefix = f'script {action} ' + ('--name ' if len(tokens) > 1 and tokens[1] == '--name' else '')
        current_os_alias = self.get_client_platform(context)
        return [CompletionCandidate(
            title=f'{prefix}{script}', insert_text=f'{prefix}{script}',
            description=f'{action.capitalize()} script: {script}',
            source=self.source, group=self.group, kind='script',
            name=script, priority=20, metadata={'script': script},
        ) for script in self._list_scripts(current_os_alias)]

    def _list_scripts(self, current_os_alias: str) -> list[str]:
        pattern = os.path.join(self.script_root, '**/*.py')
        result = []
        for file_path in glob.iglob(pattern, recursive=True):
            if not os.path.isfile(file_path):
                continue
            script = os.path.relpath(file_path, self.script_root).replace('\\', '/')
            script_name = script[:-3] if script.endswith('.py') else script
            metadata = read_script_metadata_from_file(file_path, fallback_name=script_name)
            if visible_on_platform({'path': script, 'metadata': metadata}, current_os_alias):
                result.append(script)
        return sorted(result, key=str.lower)



class ExternalToolCommandCompletionProvider(ServerCompletionSessionMixin, CommandCompletionProvider):
    """
    server xt 外部工具命令补全。
    """

    command_names = ('xt',)
    source = 'server_xt'
    group = 'external_tool'

    SUBCOMMANDS = (
        ('xt exec list', 'List available external tool execs'),
        ('xt exec info ', 'Show Exec details'),
        ('xt exec which ', 'Show installed executable path'),
        ('xt exec ', 'Run an installed external tool exec'),
        ('xt package list', 'List available packages'),
        ('xt package list --installed', 'List installed packages'),
        ('xt package install ', 'Install a package'),
        ('xt package uninstall ', 'Uninstall a package'),
        ('xt module list ', 'List package modules'),
        ('xt instance create ', 'Create an instance'),
        ('xt instance list', 'List persistent instances'),
        ('xt instance start ', 'Start an instance'),
        ('xt instance stop ', 'Stop an instance'),
        ('xt instance restart ', 'Restart an instance'),
        ('xt instance status ', 'Read instance status'),
        ('xt instance logs ', 'Read or follow instance logs'),
    )

    def __init__(self, server, external_tool_catalog_service):
        ServerCompletionSessionMixin.__init__(self, server)
        self.external_tool_catalog_service = external_tool_catalog_service

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        words = str(context.argument_text or '').strip().lower().split()
        if not words:
            return self._build_subcommand_candidates()
        if words[0] == 'exec':
            if len(words) == 1:
                return self._build_subcommand_candidates()[:4] + self._build_exec_candidates(context)
            if words[1] in {'info', 'which'}:
                return self._build_exec_candidates(context) if len(words) <= 3 else []
            if words[1] == 'list':
                return []
            return self._build_exec_candidates(context) if len(words) == 2 else []
        if words[0] not in ('package', 'module', 'instance'):
            return []
        # All suggestions replace the entire input; native arguments never enter this parser.
        if len(words) == 1:
            return [c for c in self._build_subcommand_candidates() if c.insert_text.startswith('xt ' + words[0])]
        if words[0] == 'package' and words[1] in ('install', 'uninstall') and len(words) <= 3:
            return self._build_package_candidates(context, f'xt package {words[1]} ')
        if words[0] == 'module' and words[1] == 'list' and len(words) <= 3:
            return self._build_package_candidates(context, 'xt module list ')
        if words[0] == 'instance' and words[1] in ('create', 'start', 'stop', 'restart', 'status', 'logs') and len(words) <= 3:
            return self._build_module_candidates(context, f'xt instance {words[1]} ')
        if words[0] == 'instance' and words[1] == 'list' and len(words) <= 3:
            return self._build_package_candidates(context, 'xt instance list ')
        return []

    def _build_package_candidates(self, context: CompletionContext, prefix: str):
        try:
            packages = self.external_tool_catalog_service.list_packages()
        except Exception:
            return []
        return [CompletionCandidate(title=prefix + package['id'], insert_text=prefix + package['id'],
                description=package.get('display_name') or '', source=self.source, group=self.group,
                kind='external_tool_package', name=package['id'], priority=30)
                for package in packages if package.get('id') and not package.get('error')
                and self.external_tool_catalog_service._platform_matches(package, self.get_client_platform(context))
                and self.external_tool_catalog_service._arch_matches(package, self.get_client_arch(context))]

    def _build_module_candidates(self, context: CompletionContext, prefix: str):
        try:
            modules = self.external_tool_catalog_service.list_tools()
        except Exception:
            return []
        return [CompletionCandidate(title=prefix + module['tool_id'], insert_text=prefix + module['tool_id'],
                description=module.get('display_name') or '', source=self.source, group=self.group,
                kind='external_tool_module', name=module['tool_id'], priority=30)
                for module in modules if module.get('tool_id') and module.get('execution') == 'daemon'
                and self.external_tool_catalog_service._platform_matches(module['package_meta'], self.get_client_platform(context))
                and self.external_tool_catalog_service._arch_matches(module['package_meta'], self.get_client_arch(context))]

    def _build_subcommand_candidates(self) -> list[CompletionCandidate]:
        return [
            CompletionCandidate(
                title=insert_text,
                insert_text=insert_text,
                description=description,
                source=self.source,
                group=self.group,
                kind='external_tool',
                name=insert_text.replace('xt ', '').strip() or 'xt',
                priority=20,
            )
            for insert_text, description in self.SUBCOMMANDS
        ]

    def _build_exec_candidates(self, context: CompletionContext) -> list[CompletionCandidate]:
        result = []
        try:
            exec_targets = self.external_tool_catalog_service.list_exec_targets(
                platform_alias=self.get_client_platform(context),
                arch=self.get_client_arch(context),
            )
        except Exception:
            return []

        prefix = self._resolve_exec_insert_prefix(context.argument_text)
        for item in exec_targets:
            exec_name = str(item.get('exec_name') or '').strip()
            if not exec_name:
                continue

            insert_text = f'{prefix}{exec_name}'.strip()

            result.append(CompletionCandidate(
                title=insert_text,
                insert_text=insert_text,
                description=str(item.get('description') or item.get('display_name') or item.get('package_id') or '').strip(),
                source=self.source,
                group=self.group,
                kind='external_tool_exec',
                name=exec_name,
                priority=30,
                metadata={
                    'execName': exec_name,
                    'packageId': item.get('package_id') or '',
                    'packageKey': item.get('package_key') or '',
                },
            ))
        return result

    def _resolve_exec_insert_prefix(self, argument_text: str) -> str:
        parts = str(argument_text or '').strip().split()
        if len(parts) >= 2 and parts[0] == 'exec' and parts[1] in {'info', 'which'}:
            return f'xt exec {parts[1]} '
        return 'xt exec '


class ServerFileSystemCompletionProvider(CommandCompletionProvider):
    """Complete Server-local paths for registered commands.

    Command names and directory-only restrictions belong to the caller's
    registration, not the filesystem enumeration implementation.
    """
    source = 'server_filesystem'
    group = 'filesystem'

    def __init__(self, command_names=(), *, directory_commands=()):
        self.command_names = tuple(command_names)
        self.directory_commands = frozenset(directory_commands)
        if not self.directory_commands.issubset(self.command_names):
            raise ValueError('Directory commands must be registered for Server path completion')

    def complete(self, context):
        if not self.supports(context):
            return []
        # Local path commands consume the raw path tail; spaces are not shell-tokenized.
        prefix = str(context.argument_text or '')
        directory, fragment = os.path.split(prefix)
        lookup = os.path.expanduser(directory or '.')
        directories_only = context.command_name in self.directory_commands
        with os.scandir(lookup) as entries:
            matches = [(entry.name, entry.is_dir()) for entry in entries
                       if entry.name.startswith(fragment)
                       and (entry.is_dir() or (not directories_only and entry.is_file()))]
        result = []
        matches.sort(key=lambda item: (not item[1], item[0].casefold()))
        if context.max_results > 0:
            matches = matches[:context.max_results]
        for name, is_dir in matches:
            path = os.path.join(directory, name)
            value = f'{context.command_name} {path}'
            result.append(CompletionCandidate(title=value, insert_text=value,
                source=self.source, group=self.group, kind='directory' if is_dir else 'file',
                name=name, priority=10 if is_dir else 20,
                description=path, metadata={'path': path, 'candidatePath': path, 'isDir': is_dir}))
        return result


class RemoteClientCommandCompletionProvider(CommandCompletionProvider):
    """
    代理 client 侧 CommandCompletionProvider。
    """

    command_names = ('cd', 'download', 'edit')
    source = 'client'
    group = 'client'

    def __init__(self, remote_execution_service):
        self.remote_execution_service = remote_execution_service

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        client_id = str((context.metadata or {}).get('client_id') or '').strip()
        if not client_id:
            return []

        payload = self._build_client_payload(context)
        result_payload = self.remote_execution_service.run_foreground_json_command(
            client_id,
            self._build_command(payload),
            task_type='command_candidate',
            source='web_command_autocomplete',
        )
        items = result_payload.get('items') if isinstance(result_payload, dict) else []
        return [self._candidate_from_payload(item) for item in items if isinstance(item, dict)]

    def _build_client_payload(self, context: CompletionContext) -> dict:
        payload = context.to_dict()
        metadata = dict(payload.get('metadata') or {})
        # client 侧只需要纯补全上下文，不需要 server-only 信息。
        metadata.pop('client_id', None)
        payload['metadata'] = metadata
        return payload

    def _build_command(self, payload: dict) -> str:
        return f'command_completions {encode_structured_arg(payload)}'

    def _candidate_from_payload(self, item: dict) -> CompletionCandidate:
        title = str(item.get('title') or item.get('name') or item.get('value') or '').strip()
        insert_text = str(item.get('insert_text') or item.get('name') or item.get('value') or title).strip()
        metadata = {
            key: value
            for key, value in item.items()
            if key not in {
                'name', 'title', 'value', 'insert_text', 'help',
                'group', 'source', 'kind', 'priority'
            }
        }
        return CompletionCandidate(
            title=title,
            insert_text=insert_text,
            description=str(item.get('help') or '').strip(),
            source=str(item.get('source') or self.source).strip(),
            group=str(item.get('group') or self.group).strip(),
            kind=str(item.get('kind') or 'command').strip(),
            name=insert_text,
            priority=int(item.get('priority') or 100),
            metadata=metadata,
        )


class ConfigCommandCompletionProvider(ServerCompletionSessionMixin, CommandCompletionProvider):
    """Complete configuration keys from the selected Client's real GET schema."""
    command_names = ('config',)
    source = 'server_config'
    group = 'runtime'

    def __init__(self, server, remote_execution_service):
        ServerCompletionSessionMixin.__init__(self, server)
        self.remote_execution_service = remote_execution_service
        self._cached = {}

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        import time
        from core.protocol.control import ControlDomain, ConfigurationAction
        tokens = str(context.argument_text or '').strip().split()
        if not tokens or tokens[0].lower() not in ('set', 'reset'):
            return []
        action = tokens[0].lower()
        if len(tokens) > 3 or (len(tokens) == 3 and tokens[1] != '--key'):
            return []
        if len(tokens) > 1 and tokens[1].startswith('-') and tokens[1] != '--key':
            return []
        client_id = self.get_client_id(context)
        if not client_id:
            return []
        cached = self._cached.get(client_id)
        if cached and time.monotonic() - cached[0] < 20:
            items = cached[1]
        else:
            try:
                status, result = self.remote_execution_service.run_foreground_control(
                    client_id, ControlDomain.CONFIGURATION, ConfigurationAction.GET, {},
                    task_type='runtime_config', source='completion', track_execution=False)
                if status != 1 or not isinstance(result, dict):
                    return []
                data = result.get('data') or {}
                items = data.get('items', []) if isinstance(data, dict) else []
                if not isinstance(items, list):
                    return []
            except (AttributeError, ValueError, RuntimeError, LookupError, TimeoutError):
                return []
            self._cached[client_id] = (time.monotonic(), items)
        prefix = f'config {action} ' + ('--key ' if len(tokens) > 1 and tokens[1] == '--key' else '')
        return [CompletionCandidate(
            title=f'{prefix}{item["key"]}', insert_text=f'{prefix}{item["key"]}',
            description=str(item.get('desc') or ''), source=self.source,
            group=self.group, kind='configuration', name=item['key'], priority=25 + i,
        ) for i, item in enumerate(items) if isinstance(item, dict) and item.get('key')]


class JobCommandCompletionProvider(ServerCompletionSessionMixin, CommandCompletionProvider):
    """Job names for lifecycle commands and stored reports via shared Web/CLI completion."""
    command_names = ('job',)
    source = 'server_job'
    group = 'job'

    def __init__(self, server, job_catalog_service, background_job_service):
        ServerCompletionSessionMixin.__init__(self, server)
        self.job_catalog_service = job_catalog_service
        self.background_job_service = background_job_service

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        parts = str(context.argument_text or '').lstrip().split()
        if not parts or parts[0].lower() not in ('start', 'stop', 'status', 'logs'):
            return []
        action = parts[0].lower()
        if len(parts) > 3 or (len(parts) == 3 and parts[1] != '--name'):
            return []
        if len(parts) > 1 and parts[1].startswith('-') and parts[1] != '--name':
            return []
        client_id = self.get_client_id(context)
        if not client_id:
            return []
        try:
            jobs = self.background_job_service.list_jobs(client_id) or []
        except (AttributeError, ValueError, LookupError):
            jobs = []
        active = {str(item.get('job_key') or item.get('job_name') or '').strip().casefold()
                  for item in jobs if isinstance(item, dict)
                  and str(item.get('state') or '').lower() in ('running', 'stopping')}
        if action == 'start':
            try:
                catalog = self.job_catalog_service.list_background_job_catalog()
            except (AttributeError, ValueError, LookupError):
                catalog = []
            platform = self.get_client_platform(context)
            names = [str(item.get('job_name') or '').strip() for item in (catalog or [])
                     if isinstance(item, dict) and visible_on_platform(item, platform)
                     and str(item.get('job_name') or '').strip().casefold() not in active]
        else:
            names = [str(item.get('job_key') or item.get('job_name') or '').strip()
                     for item in jobs if isinstance(item, dict)
                     and str(item.get('state') or '').lower() in ('running', 'stopping')]
        prefix = f'job {action} ' + ('--name ' if len(parts) > 1 and parts[1] == '--name' else '')
        seen = set()
        result = []
        for name in names:
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            result.append(CompletionCandidate(
                title=f'{prefix}{name}', insert_text=f'{prefix}{name}',
                description={'start': 'Start this Job', 'stop': 'Stop this running Job',
                             'status': 'Show running Job status',
                             'logs': 'View active Job reports'}[action],
                source=self.source, group=self.group, kind='job', name=name,
                priority=31 + len(result),
            ))
        return result
