import os
import re

from core.protocol.structured_arg_codec import encode_structured_arg
from core.external_tools.install_status import INSTALL_STATUS_NOT_INSTALLED, is_installed_status, normalize_install_status
from core.command_completion.models import CompletionCandidate, CompletionContext
from core.platform.normalization import normalize_platform_alias
from core.platform.catalog_visibility import visible_on_platform
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


class DeclaredServerCompletionProvider(CommandCompletionProvider):
    """Schema-selected dynamic providers, independent from command-text parsing."""

    provider_key = ''

    def target(self, context):
        if context.resolved_target is None:
            context.resolved_target = SERVER_COMMAND_REGISTRY.resolve_completion_target(context)
        target = context.resolved_target
        return target if target and target.completion.provider == self.provider_key else None

    def supports(self, context: CompletionContext) -> bool:
        return self.target(context) is not None


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
            title=value, insert_text=value, description=node.description,
            source=self.source, group=spec.group, kind='server_subcommand',
            name=node.name, priority=18 + i,
        ) for i, (value, node) in enumerate(
            SERVER_COMMAND_REGISTRY.static_completion_candidates(spec.name))]


class HelpCommandCompletionProvider(CommandCompletionProvider):
    """Discoverable help targets are generated from the Server registry."""
    command_names = ('help',)
    source = 'server'
    group = 'server'

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        targets = [('server', 'Show Server commands'), ('client', 'Show Client commands')]
        for spec in SERVER_COMMAND_REGISTRY._commands.values():
            targets.append((spec.name, spec.description))
            targets.extend((' '.join((spec.name, *path)), child.description)
                           for path, child in SERVER_COMMAND_REGISTRY.iter_public_nodes(spec.name))
        return [CompletionCandidate(
            title=f'help {name}', insert_text=f'help {name}', description=description,
            source=self.source, group=self.group, kind='server_help',
            name=name, priority=18 + index,
        ) for index, (name, description) in enumerate(targets)]


class ScriptCommandCompletionProvider(ServerCompletionSessionMixin, DeclaredServerCompletionProvider):
    """Script candidates come from the same Catalog as Web and Server CLI."""

    provider_key = 'scripts'
    source = 'script'
    group = 'script'

    def __init__(self, server, script_root: str = SCRIPT_PATH, script_catalog_service=None):
        ServerCompletionSessionMixin.__init__(self, server)
        self.script_root = script_root
        self.script_catalog_service = script_catalog_service

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        target = self.target(context)
        if target is None:
            return []
        action = target.path[-1]
        platform = self.get_client_platform(context)
        return [CompletionCandidate(
            title=target.prefix + name, insert_text=target.prefix + name,
            description=f'{action.capitalize()} script: {name}',
            source=self.source, group=self.group, kind='script',
            name=name, priority=20, metadata={'script': name},
        ) for name in self._list_scripts(platform)]

    def _list_scripts(self, platform: str) -> list[str]:
        if self.script_catalog_service is None:
            from server.application.scripts.script_catalog_service import ScriptCatalogService
            self.script_catalog_service = ScriptCatalogService(self.script_root)
        return sorted((str(item['path']) for item in self.script_catalog_service.list_scripts()
                       if visible_on_platform(item, platform)), key=str.lower)


class ExternalToolCommandCompletionProvider(ServerCompletionSessionMixin, DeclaredServerCompletionProvider):
    """XT: static command paths from Registry, dynamic targets from the selected Client."""

    provider_key = 'xt'
    source = 'server_xt'
    group = 'external_tool'

    def __init__(self, server, external_tool_catalog_service, client_lifecycle_runtime):
        ServerCompletionSessionMixin.__init__(self, server)
        self.external_tool_catalog_service = external_tool_catalog_service
        self.client_lifecycle_runtime = client_lifecycle_runtime

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        target = self.target(context)
        if target is None:
            return []
        path = target.path
        kinds = target.completion.kinds
        if 'exec' in kinds:
            # Once the executable name is complete, its native arguments belong
            # to the target executable, not to XT completion.
            source = context.raw_input or f'{context.command_name} {context.argument_text}'
            if target.tokens and source[-1:].isspace():
                return []
            return self._build_exec_candidates(context, target)
        if 'package' in kinds:
            action = path[-1] if path[1] == 'package' else ''
            return self._build_package_candidates(context, target.prefix, action=action)
        if 'module' in kinds:
            return self._build_module_candidates(context, target.prefix)
        if 'instance' in kinds:
            return self._build_instance_candidates(context, target)
        return []

    def _packages_for_client(self, context: CompletionContext) -> list[dict]:
        platform = self.get_client_platform(context)
        arch = self.get_client_arch(context)
        if not platform or not arch:
            return []
        return self.external_tool_catalog_service.list_packages_for_target(platform, arch)

    def _install_statuses(self, context: CompletionContext, packages: list[dict]) -> dict[str, str]:
        """Use the same batched Client Control as Web/XT; unknown is not uninstalled."""
        client_id = self.get_client_id(context)
        if not client_id or not packages:
            return {}
        try:
            result = self.client_lifecycle_runtime.client_install_statuses(
                client_id, packages, platform_alias=self.get_client_platform(context),
                arch=self.get_client_arch(context))
            items = result.get('items') if isinstance(result, dict) else None
            if not isinstance(items, list) or len(items) != len(packages):
                return {}
            return {str(package['id']): normalize_install_status(item)
                    for package, item in zip(packages, items)
                    if isinstance(item, dict)}
        except (AttributeError, ValueError, RuntimeError, LookupError, TimeoutError):
            return {}

    def _client_daemon_modules(self, context: CompletionContext) -> list[dict]:
        packages = {p['id'] for p in self._packages_for_client(context)}
        return [module for module in self.external_tool_catalog_service.list_tools()
                if module.get('tool_id') and module.get('execution') == 'daemon'
                and module.get('package_id') in packages]

    def _candidate(self, prefix: str, name: str, description: str, kind: str) -> CompletionCandidate:
        value = prefix + name
        return CompletionCandidate(title=value, insert_text=value, description=description,
                                   source=self.source, group=self.group, kind=kind,
                                   name=name, priority=30)

    def _build_package_candidates(self, context: CompletionContext, prefix: str, action: str = ''):
        try:
            packages = self._packages_for_client(context)
            statuses = self._install_statuses(context, packages) if action else {}
        except (AttributeError, ValueError, RuntimeError, LookupError):
            return []
        return [self._candidate(prefix, package['id'], package.get('display_name') or '',
                                'external_tool_package')
                for package in packages
                if not action or (is_installed_status(statuses.get(package['id'])) if action == 'uninstall'
                                  else statuses.get(package['id']) == INSTALL_STATUS_NOT_INSTALLED)]

    def _build_module_candidates(self, context: CompletionContext, prefix: str):
        try:
            modules = self._client_daemon_modules(context)
            packages = self._packages_for_client(context)
            statuses = self._install_statuses(context, packages)
        except (AttributeError, ValueError, RuntimeError, LookupError):
            return []
        return [self._candidate(prefix, module['tool_id'], module.get('display_name') or '',
                                'external_tool_module')
                for module in modules if is_installed_status(statuses.get(module['package_id']))]

    def _build_instance_candidates(self, context: CompletionContext, target):
        action = target.path[-1]
        # The Registry handles syntax; completion only selects candidates with real Client state.
        client_id = self.get_client_id(context)
        if not client_id:
            return []
        try:
            modules = self._client_daemon_modules(context)
            if not modules:
                return []
            response = self.client_lifecycle_runtime.list_all_client_instances(client_id, modules)
            rows = response.get('items') if isinstance(response, dict) else None
            if not isinstance(rows, list):
                return []
            installed = {}
            if action == 'start':
                packages = self._packages_for_client(context)
                installed = self._install_statuses(context, packages)
        except (AttributeError, ValueError, RuntimeError, LookupError, TimeoutError):
            return []
        module_by_id = {m['tool_id']: m for m in modules}
        parts = target.tokens
        target_module = ''
        for index, token in enumerate(parts):
            if token == '--module' and index + 1 < len(parts):
                target_module = parts[index + 1]
            elif token.startswith('--module='):
                target_module = token.partition('=')[2]
        if not target_module and parts and not parts[0].startswith('-'):
            target_module = parts[0]
        named = any(token in ('--name', '--module') or
                    token.startswith(('--name=', '--module=')) for token in parts)
        prefix = f'xt instance {action} '
        if named and target_module:
            prefix += f'--module {target_module} --name '
        result, seen = [], set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            tool = str(row.get('tool_id') or '').strip()
            instance_id = str(row.get('instance_id') or '').strip()
            meta = module_by_id.get(tool)
            if not meta or not instance_id or (target_module and tool != target_module):
                continue
            status = str(row.get('status') or '').lower()
            running = row.get('running') is True or status == 'running'
            stopping = status == 'stopping'
            if action == 'start' and (running or stopping or not is_installed_status(installed.get(meta['package_id']))):
                continue
            if action == 'stop' and not (running or stopping):
                continue
            if action == 'restart' and not running:
                continue
            name = instance_id if (named and target_module) else (f'--module {tool} --name {instance_id}' if named else f'{tool} {instance_id}')
            if name in seen:
                continue
            seen.add(name)
            result.append(self._candidate(prefix, name,
                f'{meta.get("display_name") or tool} — {row.get("status") or ("running" if running else "stopped")}',
                'external_tool_instance'))
        return result

    def _build_exec_candidates(self, context: CompletionContext, target) -> list[CompletionCandidate]:
        try:
            targets = self.external_tool_catalog_service.list_exec_targets(
                platform_alias=self.get_client_platform(context), arch=self.get_client_arch(context))
            require_installed = target.path[-1] != 'info'
            statuses = {}
            if require_installed:
                packages = self._packages_for_client(context)
                statuses = self._install_statuses(context, packages)
        except (AttributeError, ValueError, RuntimeError, LookupError):
            return []
        prefix = target.prefix
        result = []
        for item in targets:
            exec_name = str(item.get('exec_name') or '').strip()
            if not exec_name or (require_installed and not is_installed_status(statuses.get(item.get('package_id')))):
                continue
            result.append(CompletionCandidate(
                title=prefix + exec_name, insert_text=prefix + exec_name,
                description=str(item.get('description') or item.get('display_name') or item.get('package_id') or '').strip(),
                source=self.source, group=self.group, kind='external_tool_exec',
                name=exec_name, priority=30,
                metadata={'execName': exec_name, 'packageId': item.get('package_id') or '',
                          'packageKey': item.get('package_key') or ''},
            ))
        return result



class ServerFileSystemCompletionProvider(CommandCompletionProvider):
    """Resolve Server-local path candidates from declared command CompletionSpec."""

    provider_key = 'filesystem'
    source = 'server_filesystem'
    group = 'filesystem'

    def __init__(self, registry=SERVER_COMMAND_REGISTRY):
        self.command_registry = registry

    def _path_query(self, context):
        target = self.command_registry.resolve_completion_target(context)
        if not target or target.completion.provider != 'filesystem':
            return None
        source = context.raw_input or f'{context.command_name} {context.argument_text}'
        return source[len(target.prefix):], target.completion.kinds

    def supports(self, context: CompletionContext) -> bool:
        return self._path_query(context) is not None

    def complete(self, context):
        query = self._path_query(context)
        if query is None:
            return []
        prefix, kinds = query
        directory, fragment = os.path.split(prefix)
        lookup = os.path.expanduser(directory or '.')
        allow_files = 'file' in kinds
        allow_directories = 'directory' in kinds
        with os.scandir(lookup) as entries:
            matches = [(entry.name, entry.is_dir()) for entry in entries
                       if entry.name.startswith(fragment)
                       and ((entry.is_dir() and allow_directories) or
                            (entry.is_file() and allow_files))]
        result = []
        matches.sort(key=lambda item: (not item[1], item[0].casefold()))
        if context.max_results > 0:
            matches = matches[:context.max_results]
        # The insert text remains a complete command for both Web and RCHCLI.
        prefix_command = (context.raw_input[:len(context.raw_input) - len(prefix)]
                          if context.raw_input else f'{context.command_name} ')
        for name, is_dir in matches:
            path = os.path.join(directory, name)
            value = prefix_command + path
            result.append(CompletionCandidate(title=value, insert_text=value,
                source=self.source, group=self.group, kind='directory' if is_dir else 'file',
                name=name, priority=10 if is_dir else 20,
                description=path, metadata={'path': path, 'candidatePath': path, 'isDir': is_dir}))
        return result


class RemoteClientCommandCompletionProvider(ServerCompletionSessionMixin, CommandCompletionProvider):
    """Request Client-declared completion through the dedicated read-only protocol."""

    source = 'client'
    group = 'client'

    def __init__(self, server, remote_execution_service):
        ServerCompletionSessionMixin.__init__(self, server)
        self.remote_execution_service = remote_execution_service

    def _manifest_entry(self, context):
        session = self.get_session(context)
        manifest = getattr(getattr(session, 'session_info', None), 'command_manifest', None) or []
        command_name = str(context.command_name or '').strip().lower()
        if command_name == 'acmd':
            subcommand = str(context.argument_text or '').strip().split(maxsplit=1)
            if not subcommand:
                return None
            target_name = f'acmd {subcommand[0].lower()}'
        else:
            target_name = command_name
        return next((item for item in manifest
                     if isinstance(item, dict)
                     and str(item.get('name') or '').strip().lower() == target_name), None)

    def supports(self, context: CompletionContext) -> bool:
        metadata = context.metadata or {}
        if isinstance(metadata.get('completion_spec'), dict):
            return True
        entry = self._manifest_entry(context)
        completion = entry.get('completion') if isinstance(entry, dict) else None
        return bool(completion)

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        client_id = self.get_client_id(context)
        if not client_id:
            return []
        payload = {
            'raw_input': context.raw_input,
            'cursor_position': (context.metadata or {}).get('raw_cursor_position', len(context.raw_input)),
            'max_results': context.max_results,
        }
        override = (context.metadata or {}).get('completion_spec')
        if isinstance(override, dict):
            payload['completion'] = override
        result_payload = self.remote_execution_service.run_completion(client_id, payload)
        items = result_payload.get('items') if isinstance(result_payload, dict) else []
        return [self._candidate_from_payload(item) for item in items if isinstance(item, dict)]

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


class ConfigCommandCompletionProvider(ServerCompletionSessionMixin, DeclaredServerCompletionProvider):
    """Complete configuration keys from the selected Client's real GET schema."""
    provider_key = 'configuration'
    source = 'server_config'
    group = 'runtime'

    def __init__(self, server, remote_execution_service):
        ServerCompletionSessionMixin.__init__(self, server)
        self.remote_execution_service = remote_execution_service
        self._cached = {}

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        import time
        from core.protocol.control import ControlDomain, ConfigurationAction
        target = self.target(context)
        if target is None:
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
                    task_type='runtime_config', source='completion')
                if status != 1 or not isinstance(result, dict):
                    return []
                data = result.get('data') or {}
                items = data.get('items', []) if isinstance(data, dict) else []
                if not isinstance(items, list):
                    return []
            except (AttributeError, ValueError, RuntimeError, LookupError, TimeoutError):
                return []
            self._cached[client_id] = (time.monotonic(), items)
        prefix = target.prefix
        return [CompletionCandidate(
            title=f'{prefix}{item["key"]}', insert_text=f'{prefix}{item["key"]}',
            description=str(item.get('desc') or ''), source=self.source,
            group=self.group, kind='configuration', name=item['key'], priority=25 + i,
        ) for i, item in enumerate(items) if isinstance(item, dict) and item.get('key')]


class JobCommandCompletionProvider(ServerCompletionSessionMixin, DeclaredServerCompletionProvider):
    """Job names for lifecycle commands and stored reports via shared Web/CLI completion."""
    provider_key = 'jobs'
    source = 'server_job'
    group = 'job'

    def __init__(self, server, job_catalog_service, background_job_service):
        ServerCompletionSessionMixin.__init__(self, server)
        self.job_catalog_service = job_catalog_service
        self.background_job_service = background_job_service

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        target = self.target(context)
        if target is None:
            return []
        action = target.path[-1]
        client_id = self.get_client_id(context)
        if not client_id:
            return []
        try:
            jobs = self.background_job_service.list_jobs(client_id) or []
        except (AttributeError, ValueError, LookupError):
            jobs = []
        from server.application.jobs.background_job_store import BackgroundJobStore
        active_states = BackgroundJobStore.ACTIVE_STATES
        active = {str(item.get('job_key') or item.get('job_name') or '').strip().casefold()
                  for item in jobs if isinstance(item, dict)
                  and str(item.get('state') or '').lower() in active_states}
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
                     and str(item.get('state') or '').lower() in active_states]
        prefix = target.prefix
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
