import glob
import json
import os
import re
import shlex

from core.protocol.structured_arg_codec import decode_structured_arg
from core.utils.command_output import (
    StructuredCommandResult,
    parse_output_format,
    render_structured_result, strip_output_format_arg,
)
from core.utils.formatting import format_dict
from core.utils.parsing import scan_args
from core.utils.script_metadata import read_script_metadata_from_file
from core.platform.catalog_visibility import visible_on_platform
from server.application.auth.script_grant_service import SCRIPT_GRANT_REQUEST_KEY
from server.application.command.command_execution_event import CommandExecutionEvent
from server.application.history.quick_history import QuickHistoryRecordPolicy
from server.config.config import SCRIPT_PATH


class UploadBuiltinSupport:
    """
    upload 相关内建命令支持。
    """

    def __init__(self, conn, remote_execution_service, history_entry_id_provider):
        self.conn = conn
        self.remote_execution_service = remote_execution_service
        self.history_entry_id_provider = history_entry_id_provider

    def upload(self, filename):
        if not os.path.isfile(filename):
            raise FileNotFoundError(f"File does not exist: {filename}")

        history_entry_id = self.history_entry_id_provider()

        event_iter = self.remote_execution_service.iter_upload_events(
            self.conn,
            filename,
            remote_path='',
            history_entry_id=history_entry_id,
            source='cli',
            task_id='',
            command=f'upload {os.path.basename(filename)}',
        )

        for event in event_iter:
            if event.event_type == CommandExecutionEvent.STARTED:
                continue

            if event.event_type == CommandExecutionEvent.COMPLETED:
                continue

            if event.event_type == CommandExecutionEvent.PROGRESS:
                if event.text:
                    yield 1, event.text
                continue

            if event.event_type == CommandExecutionEvent.CHUNK:
                yield event.status, event.text
                continue

            if event.event_type == CommandExecutionEvent.ERROR:
                yield 0, event.text
                continue

            if event.event_type == CommandExecutionEvent.CANCELLED:
                if event.payload.get('terminal'):
                    continue
                yield 0, event.text or 'cancelled'


class ScriptBuiltinSupport:
    """
    script builtin: list / view / exec / run.
    """

    def __init__(self, plan_builder, plan_executor_factory, conn=None):
        self.plan_builder = plan_builder
        self.plan_executor_factory = plan_executor_factory
        self.conn = conn

    def _platform(self):
        info = getattr(self.conn, 'session_info', None)
        return str(getattr(info, 'os_alias', '') or '')

    def script(self, subcommand, tail=''):
        """Execute a validated registry subcommand without leaking transport detail."""
        if subcommand == 'list':
            from core.utils.command_output import parse_output_format, render_structured_result, StructuredCommandResult
            text = str(tail or '').strip()
            if text not in ('', '--json'):
                yield 0, 'Usage: script list [--json]'
                return
            if text == '--json':
                rows = []
                for item in self.list_script_catalog():
                    parameters = (item['metadata'] or {}).get('params') or []
                    if isinstance(parameters, dict):
                        param_names = list(parameters.keys())
                    elif isinstance(parameters, list):
                        param_names = [p.get('name', '') for p in parameters if isinstance(p, dict)]
                    else:
                        param_names = []
                    rows.append({'name': item['path'], 'display_name': item['display_name'],
                                 'description': item['description'], 'params': param_names})
                yield render_structured_result(
                    StructuredCommandResult(status=1, data=rows, shape='table'), output_format='json')
                return
            yield 1, '\n'.join(self.list_scripts())
            return
        if subcommand == 'view':
            try:
                args = shlex.split(tail)
            except ValueError as exc:
                yield 0, str(exc)
                return
            if len(args) != 1:
                yield 0, 'Usage: script view <path>'
                return
            with open(self._resolve_script_path(args[0]), 'rt', encoding='utf-8') as source:
                yield 1, source.read()
            return
        if subcommand == 'exec':
            if not str(tail or '').strip():
                yield 0, 'Usage: script exec <path> [options]'
                return
            yield from self.execute_script_file(tail)
            return
        if subcommand == 'run':
            if not str(tail or '').strip():
                yield 0, 'Usage: script run <__json__:payload>'
                return
            yield from self.execute_script_payload(tail)
            return
        raise ValueError(f'Unsupported script subcommand: {subcommand}')

    def _iter_script_files(self):
        return glob.iglob(os.path.join(SCRIPT_PATH, '**/*.py'), recursive=True)

    def list_scripts(self):
        return [item['path'] for item in self.list_script_catalog()]

    def list_script_catalog(self):
        items = []
        for file_path in self._iter_script_files():
            rel_path = os.path.relpath(file_path, SCRIPT_PATH).replace('\\', '/')
            script_name = rel_path[:-3] if rel_path.endswith('.py') else rel_path
            metadata = read_script_metadata_from_file(file_path, fallback_name=script_name)
            items.append({
                'script_name': script_name,
                'path': rel_path,
                'display_name': str(metadata.get('display_name') or script_name.split('/')[-1]).strip() or script_name,
                'description': str(metadata.get('description') or '').strip(),
                'metadata': metadata,
            })
        return sorted(
            (item for item in items if visible_on_platform(item, self._platform())),
            key=lambda item: item.get('path', '').lower(),
        )

    def _resolve_script_path(self, script_name: str) -> str:
        script_path = os.path.realpath(os.path.join(SCRIPT_PATH, script_name))
        script_root = os.path.realpath(SCRIPT_PATH)
        if os.path.commonpath((script_root, script_path)) != script_root:
            raise ValueError('Script path is outside the Server Script directory')
        if os.path.isfile(script_path):
            return script_path

        candidate = os.path.realpath(script_path + '.py')
        if os.path.commonpath((script_root, candidate)) == script_root and os.path.isfile(candidate):
            return candidate

        raise FileNotFoundError(f"Script not found: {script_path}")

    def _build_script_plan(self, script_text: str, script_args: list):
        return self.plan_builder.build_script_plan(script_text, scan_args(script_args))

    def _decode_script_payload_arg(self, raw):
        try:
            return decode_structured_arg(raw, require_prefix=True)
        except Exception as e:
            raise ValueError(f'Invalid script run payload: {e}') from e

    def execute_script_file(self, filename: str):
        parts = shlex.split(filename)
        script_path = self._resolve_script_path(parts[0])
        plan_executor = self.plan_executor_factory()

        with open(script_path, 'rt', encoding='utf-8') as file_obj:
            try:
                plan = self._build_script_plan(file_obj.read(), parts[1:])
                for item in plan_executor(plan)():
                    yield item
            except UnicodeDecodeError:
                raise RuntimeError(f"Unable to read file: {script_path}")

    def execute_script_payload(self, payload_text: str):
        payload = self._decode_script_payload_arg(payload_text)
        if not isinstance(payload, dict):
            raise ValueError('Invalid script run payload')

        script_name = str(payload.get('script_name') or payload.get('name') or '').strip()
        if not script_name:
            raise ValueError('script_name is required')

        params = payload.get('params') or {}
        if not isinstance(params, dict):
            raise ValueError('params must be an object')

        script_extra = dict(params)
        script_extra['__script_name__'] = script_name
        grant_request = payload.get('script_grant_request')
        if isinstance(grant_request, dict) and grant_request:
            script_extra[SCRIPT_GRANT_REQUEST_KEY] = grant_request

        script_path = self._resolve_script_path(script_name)
        plan_executor = self.plan_executor_factory()

        with open(script_path, 'rt', encoding='utf-8') as file_obj:
            try:
                plan = self.plan_builder.build_script_plan(file_obj.read(), script_extra)
                for item in plan_executor(plan)():
                    yield item
            except UnicodeDecodeError:
                raise RuntimeError(f"Unable to read file: {script_path}")



import re

from core.utils.command_output import (
    StructuredCommandResult,
    parse_output_format,
    render_structured_result,
    strip_output_format_arg,
)


import re

from core.utils.command_output import (
    StructuredCommandResult,
    parse_output_format,
    render_structured_result,
    strip_output_format_arg,
)


class AliasBuiltinSupport:
    """
    alias 子命令支持：

    - alias / alias list [--json]
    - alias set [--platform <supported>] name = command
    - alias unset [--platform <supported>] name
    """

    ANY_PLATFORM_OPTION_PATTERN = re.compile(
        r'^(?:--platform|-p)\s+(\S+)\b',
        re.IGNORECASE,
    )

    def __init__(self, alias_manager, conn):
        self.alias_manager = alias_manager
        self.conn = conn

    def _parse_platform_option(self, arg_text: str) -> tuple[str, str]:
        text = str(arg_text or '').strip()
        matched = self.ANY_PLATFORM_OPTION_PATTERN.match(text)
        if matched is None:
            return '', text

        raw_platform = matched.group(1)
        try:
            platform_name = self.alias_manager.normalize_platform(raw_platform)
        except ValueError:
            raise ValueError(
                f"Unsupported platform: {raw_platform}. "
                f"Supported platforms: {', '.join(self.alias_manager.get_supported_platforms())}"
            )

        remaining = text[matched.end():].strip()
        return platform_name, remaining

    def _resolve_target_platform(self, platform_name: str) -> str:
        return platform_name or 'common'

    def _get_runtime_platform(self) -> str:
        """
        直接复用 AliasManager 的连接平台识别逻辑。
        未映射到受支持平台时返回空串，resolve 时只显示 common。
        """
        platform_name = self.alias_manager.get_platform_for_connection(self.conn)
        if platform_name in self.alias_manager.get_supported_platforms():
            return platform_name
        return ''

    def _normalize_alias_rows(self, alias_map: dict, platform_name: str) -> list[dict]:
        rows = []
        for alias_name in sorted((alias_map or {}).keys()):
            rows.append({
                'platform': platform_name,
                'alias': alias_name or '',
                'command': alias_map.get(alias_name) or '',
            })
        return rows

    def _build_resolved_alias_payload(self) -> list[dict]:
        """
        alias resolve:
        - 显示 common + 当前平台
        - 当前平台无法识别时，只显示 common
        - platform 字段表示“该 alias 最终来自哪一层”
        """
        runtime_platform = self._get_runtime_platform()

        common_aliases = self.alias_manager.list_aliases_for_platform('common', conn=self.conn) or {}
        platform_aliases = {}

        if runtime_platform and runtime_platform != 'common':
            platform_aliases = self.alias_manager.list_aliases_for_platform(runtime_platform, conn=self.conn) or {}

        merged = dict(common_aliases)
        merged.update(platform_aliases)

        rows = []
        for alias_name, command_text in merged.items():
            source_platform = runtime_platform if runtime_platform and alias_name in platform_aliases else 'common'
            rows.append({
                'platform': source_platform,
                'alias': alias_name or '',
                'command': command_text or '',
            })

        rows.sort(key=lambda item: (
            str(item.get('platform') or ''),
            str(item.get('alias') or ''),
        ))
        return rows

    def list_aliases(self):
        """
        给自动补全/旧逻辑使用：返回当前连接可用 alias（dict）
        """
        return self.alias_manager.list_aliases(conn=self.conn)

    def list_resolved_aliases(self) -> list[dict]:
        """
        给自动补全/展示使用：返回 common + 当前平台 合并后的结构化结果
        """
        return self._build_resolved_alias_payload()

    def _render_table_result(self, payload: list[dict], output_format: str):
        return render_structured_result(
            StructuredCommandResult(
                status=1,
                data=payload,
                shape='table',
            ),
            output_format=output_format,
        )

    def _alias_set(self, arg=''):
        text = str(arg or '').strip()
        platform_name, remaining_text = self._parse_platform_option(text)
        target_platform = self._resolve_target_platform(platform_name)

        if not remaining_text or '=' not in remaining_text:
            raise ValueError(
                f"Expected format: alias set [--platform {'|'.join(self.alias_manager.get_supported_platforms())}] name = command"
            )

        try:
            alias_name, command_text = [part.strip() for part in remaining_text.split('=', 1)]

            if not alias_name:
                raise ValueError("Missing alias name")
            if not command_text:
                raise ValueError("Missing alias command")

            self.alias_manager.add_alias(alias_name, command_text, platform=target_platform)
            yield 1, f'Alias saved [{target_platform}]: {alias_name} -> {command_text}'
        except Exception as e:
            raise ValueError(f'Failed to save alias: {e}')

    def _alias_unset(self, arg=''):
        text = str(arg or '').strip()
        platform_name, remaining_text = self._parse_platform_option(text)
        target_platform = self._resolve_target_platform(platform_name)

        alias_name = remaining_text.strip()
        if not alias_name:
            raise ValueError("Missing alias name")

        try:
            self.alias_manager.remove_alias(alias_name, platform=target_platform)
            yield 1, f"Alias removed [{target_platform}]: {alias_name}"
        except KeyError:
            raise ValueError(f"Alias not found: {alias_name}")

    def _alias_list(self, arg=''):
        output_format = parse_output_format(arg)
        remaining = strip_output_format_arg(arg)
        if str(remaining or '').strip():
            raise ValueError('Usage: alias [list] [--json]')
        yield self._render_table_result(self._build_resolved_alias_payload(), output_format)

    def execute_subcommand(self, subcommand, remaining=''):
        if subcommand == 'list':
            yield from self._alias_list(remaining)
        elif subcommand == 'set':
            yield from self._alias_set(remaining)
        elif subcommand == 'unset':
            yield from self._alias_unset(remaining)
        else:
            raise ValueError(f'Unsupported alias subcommand: {subcommand}')

    def alias(self, arg=''):
        from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
        _, subcommand, remaining = SERVER_COMMAND_REGISTRY.parse('alias', arg)
        yield from self.execute_subcommand(subcommand, remaining)


class PinnedPathBuiltinSupport:
    """
    gopin 相关内建命令支持。
    """

    def __init__(self, pinned_path_store, command_history, conn, history_entry_id_provider, command_processor_factory):
        self.pinned_path_store = pinned_path_store
        self.command_history = command_history
        self.conn = conn
        self.history_entry_id_provider = history_entry_id_provider
        self.command_processor_factory = command_processor_factory


    def _get_machine_id(self) -> str:
        session_info = getattr(self.conn, 'session_info', None)
        return getattr(session_info, 'machine_id', '') or 'unknown_machine'


    def list_pinned_paths(self) -> list[dict]:
        return self.pinned_path_store.list_items(self._get_machine_id())


    def _build_cd_command(self, path: str) -> str:
        return f'cd {path}'


    def gopin(self, arg=''):
        name = str(arg or '').strip()
        items = self.list_pinned_paths()

        if not name:
            if not items:
                yield 1, 'No saved pinned paths for current host'
                return

            lines = []
            for item in items:
                lines.append(f'{item.get("display_name", "")} -> {item.get("path", "")}')
            yield 1, '\n'.join(lines)
            return

        matched_item = self.pinned_path_store.get_item_by_name(self._get_machine_id(), name)
        if matched_item is None:
            raise ValueError(f'Pinned path not found: {name}')

        target_path = str(matched_item.get('path') or '').strip()
        resolved_command = self._build_cd_command(target_path)

        # gopin 作为快捷命令，history 保留原始 gopin 输入，不再改写成 cd 结果。
        yield 1, f'gopin {name} -> {resolved_command}'

        command_processor = self.command_processor_factory()
        executor = command_processor(resolved_command)
        for item in executor():
            yield item


class HistoryBuiltinSupport:
    """
    history 相关内建命令支持。
    """

    HISTORY_RUN_PATTERN = re.compile(r'^run\s+(\d+)$', re.IGNORECASE)
    HISTORY_SHORTCUT_PATTERN = re.compile(r'^!(\d+)$')

    def __init__(self, command_history, conn, history_entry_id_provider, command_processor_factory):
        self.command_history = command_history
        self.conn = conn
        self.history_entry_id_provider = history_entry_id_provider
        self.command_processor_factory = command_processor_factory

    def _is_meta_history_command(self, command_text: str) -> bool:
        text = str(command_text or '').strip()
        if not text:
            return False
        return QuickHistoryRecordPolicy.is_history_replay_command(text)

    def _get_resolvable_quick_history(self) -> list:
        """
        获取可用于 history run 的 quick history 视图。

        这里会过滤掉 history run / !index 这类“元命令”，避免：
        - 当前正在执行的 history run 把 quick history index 顶掉
        - history replay 命令本身污染可执行历史列表
        """
        entries = self.command_history.get_history_for_connection(self.conn) or []
        filtered = []

        for item in entries:
            command_text = str(item.get('command') or '').strip()
            if self._is_meta_history_command(command_text):
                continue

            cloned = dict(item)
            cloned['index'] = len(filtered) + 1
            filtered.append(cloned)

        return filtered

    def _resolve_history_command_by_index(self, history_index: int) -> str:
        entries = self._get_resolvable_quick_history()

        for item in entries:
            current_index = int(item.get('index', 0) or 0)
            if current_index != history_index:
                continue

            command_text = str(item.get('command') or '').strip()
            if command_text:
                return command_text
            break

        raise ValueError(f'History index not found: {history_index}')

    def _run_history_item(self, history_index: int):
        resolved_command = self._resolve_history_command_by_index(history_index)
        # Keep the outer invocation (`history run N` or `!N`); the nested
        # execution plan supplies the actual resolved Client command.
        yield 1, f'sending command: {resolved_command}'

        command_processor = self.command_processor_factory()
        executor = command_processor(resolved_command)
        for item in executor():
            yield item

    def history(self, arg):
        arg_text = (arg or '').strip()

        if not arg_text:
            entries = self._get_resolvable_quick_history()
            if not entries:
                yield 1, 'No command history available\n\nTip: use history run <index> or !<index> to run a history item quickly'
                return

            lines = []
            for item in entries:
                lines.append(
                    f'{item.get("index", 0):>3}  '
                    f'{item.get("command", "")}'
                )

            yield 1, '\n'.join(lines)
            yield 1, '\nTip: use history run <index> or !<index> to run a history item quickly'
            return

        if arg_text == 'clear':
            self.command_history.clear_history_for_connection(self.conn)
            yield 1, 'Command history cleared'
            return

        matched = self.HISTORY_RUN_PATTERN.fullmatch(arg_text)
        if matched:
            history_index = int(matched.group(1))
            for item in self._run_history_item(history_index):
                yield item
            return

        raise ValueError('Unsupported history command. Use: history | history run <index> | history clear')


class RttBuiltinSupport:
    """
    rtt 相关内建命令支持。
    """

    def __init__(self, conn):
        self.conn = conn

    def rtt(self, arg=''):
        payload = {
            'connection_state': self.conn.context.connected_at and (
                'offline' if self.conn.context.disconnected_at else 'online'
            ) or 'unknown',
            'connected_at': self.conn.context.connected_at or '',
            'last_seen_at': self.conn.context.last_seen_at or '',
            'last_heartbeat_sent_at': self.conn.context.last_heartbeat_sent_at or '',
            'last_heartbeat_ack_at': self.conn.context.last_heartbeat_ack_at or '',
            'last_rtt_ms': self.conn.context.last_rtt_ms if self.conn.context.last_rtt_ms is not None else '',
            'last_heartbeat_id': self.conn.context.last_heartbeat_id if self.conn.context.last_heartbeat_id is not None else '',
        }

        output_format = parse_output_format(arg)
        arg = strip_output_format_arg(arg)

        yield render_structured_result(
            StructuredCommandResult(
                status=1,
                data=payload,
                shape='dict',
                width=24,
            ),
            output_format=output_format,
        )
