import glob
import os
import re

from core.command_completion.models import CompletionCandidate, CompletionContext
from core.platform.normalization import normalize_platform_alias
from core.command_completion.provider import CommandCompletionProvider
from server.application.history.history_record_policy import CommandHistoryRecordPolicy
from server.config.config import SCRIPT_PATH


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
            if CommandHistoryRecordPolicy.is_history_replay_command(command_text):
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


class AliasCommandCompletionProvider(CommandCompletionProvider):
    """
    server alias 菜单子命令补全；不读取 alias.json，不补具体别名。
    """

    command_names = ('alias',)
    source = 'server_alias'
    group = 'alias'

    def __init__(self, alias_manager):
        self.alias_manager = alias_manager

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        return self._build_candidates()

    def _build_candidates(self) -> list[CompletionCandidate]:
        platforms = '|'.join(self.alias_manager.get_supported_platforms())
        menu_items = (
            ('alias resolve', 'Show resolved aliases for current client platform'),
            ('alias set ', f'Create or update an alias: alias set [--platform {platforms}] name = command'),
            ('alias unset ', f'Remove an alias: alias unset [--platform {platforms}] name'),
            ('alias list', 'List all platform aliases'),
            ('alias reload', 'Reload alias definitions'),
        )
        result = []
        for index, (insert_text, description) in enumerate(menu_items):
            result.append(CompletionCandidate(
                title=insert_text,
                insert_text=insert_text,
                description=description,
                source=self.source,
                group=self.group,
                kind='alias_menu',
                name=insert_text.replace('alias ', '').strip() or 'alias',
                priority=20 + index,
            ))
        return result

class HttpctlCommandCompletionProvider(CommandCompletionProvider):
    """
    server httpctl 子命令补全。
    """

    command_names = ('httpctl',)
    source = 'server_httpctl'
    group = 'control'

    ACTIONS = (
        ('stop', 'Stop current client through the independent HTTP control channel'),
        ('restart', 'Restart current client through the independent HTTP control channel'),
        ('start', 'Start a new client instance through the independent HTTP control channel'),
    )

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        return [
            CompletionCandidate(
                title=f'httpctl {name}',
                insert_text=f'httpctl {name}',
                description=description,
                source=self.source,
                group=self.group,
                kind='control',
                name=name,
                priority=20,
            )
            for name, description in self.ACTIONS
        ]


class ExecScriptCommandCompletionProvider(ServerCompletionSessionMixin, CommandCompletionProvider):
    """
    server exec 脚本补全。
    """

    command_names = ('exec',)
    source = 'script'
    group = 'script'

    def __init__(self, server, script_root: str = SCRIPT_PATH):
        ServerCompletionSessionMixin.__init__(self, server)
        self.script_root = script_root

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        current_os_alias = self.get_client_platform(context)
        result = []

        for script in self._list_scripts(current_os_alias):
            insert_text = f'exec {script}'
            result.append(CompletionCandidate(
                title=insert_text,
                insert_text=insert_text,
                description=f'Execute script: {script}',
                source=self.source,
                group=self.group,
                kind='script',
                name=script,
                priority=20,
                metadata={
                    'script': script,
                },
            ))

        return result

    def _list_scripts(self, current_os_alias: str) -> list[str]:
        pattern = os.path.join(self.script_root, '**/*.py')
        result = []
        for file_path in glob.iglob(pattern, recursive=True):
            if not os.path.isfile(file_path):
                continue
            script = os.path.relpath(file_path, self.script_root).replace('\\', '/')
            if self._should_show_script(script, current_os_alias):
                result.append(script)
        return sorted(result, key=str.lower)

    def _should_show_script(self, script: str, current_os_alias: str) -> bool:
        root = script.replace('\\', '/').split('/')[0].strip().lower()
        normalized_root = self._normalize_platform_alias(root)
        if not normalized_root:
            return False
        if normalized_root in {'common', 'shared'}:
            return True
        if not current_os_alias:
            return True
        return normalized_root == current_os_alias


class ExternalToolCommandCompletionProvider(ServerCompletionSessionMixin, CommandCompletionProvider):
    """
    server xt 外部工具命令补全。
    """

    command_names = ('xt',)
    source = 'server_xt'
    group = 'external_tool'

    SUBCOMMANDS = (
        ('xt list', 'List external tool execs'),
        ('xt info ', 'Show external tool exec info'),
        ('xt which ', 'Show external tool executable path'),
        ('xt run ', 'Run external tool exec with raw args'),
    )

    def __init__(self, server, external_tool_catalog_service):
        ServerCompletionSessionMixin.__init__(self, server)
        self.external_tool_catalog_service = external_tool_catalog_service

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        items = self._build_subcommand_candidates()
        items.extend(self._build_exec_candidates(context))
        return items

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
            if prefix == 'xt run ':
                insert_text = f'{insert_text} '

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
        if parts and parts[0] in {'info', 'which', 'run'}:
            return f'xt {parts[0]} '
        return 'xt '


class RemoteClientCommandCompletionProvider(CommandCompletionProvider):
    """
    代理 client 侧 CommandCompletionProvider。
    """

    command_names = ('cd', 'set', 'download')
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
        import base64
        import json

        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        encoded = base64.urlsafe_b64encode(raw).decode('utf-8')
        return f'command_completions __json__:{encoded}'

    def _candidate_from_payload(self, item: dict) -> CompletionCandidate:
        title = str(item.get('title') or item.get('template') or item.get('value') or item.get('name') or '').strip()
        insert_text = str(item.get('insert_text') or item.get('template') or item.get('value') or title).strip()
        metadata = {
            key: value
            for key, value in item.items()
            if key not in {
                'name', 'title', 'template', 'value', 'insert_text', 'help',
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
            name=str(item.get('name') or title).strip(),
            priority=int(item.get('priority') or 100),
            metadata=metadata,
        )
