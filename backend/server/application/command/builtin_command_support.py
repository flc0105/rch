import json
import os

from core.utils.formatting import format_dict
from server.application.scripts.script_run_service import prepare_script_control
from core.platform.catalog_visibility import visible_on_platform
from server.application.command.command_execution_event import CommandExecutionEvent
from core.protocol.message_queue import ResultChunk
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

    def upload(self, invocation):
        """Project transfer progress and one authoritative terminal Result."""
        from core.protocol.result_envelope import ResultEnvelope
        from core.utils.command_output import render_result_payload

        filename = os.path.expanduser(invocation.arguments['command'])
        if not os.path.isfile(filename):
            raise FileNotFoundError(f"File does not exist: {filename}")

        history_entry_id = self.history_entry_id_provider()
        foreground = getattr(self.conn, 'get_foreground_task', lambda: None)() or {}
        if history_entry_id and foreground.get('history_entry_id') != history_entry_id:
            foreground = {}

        events = self.remote_execution_service.iter_upload_events(
            self.conn, filename, remote_path='', history_entry_id=history_entry_id,
            source='cli', task_id=foreground.get('task_id') or '',
            tab_id=foreground.get('tab_id') or '',
            command=f'upload {os.path.basename(filename)}',
        )
        failure_message = ''
        cancelled = False
        for event in events:
            if event.event_type == CommandExecutionEvent.PROGRESS:
                # Progress is a distinct protocol event, not a completed Result.
                if event.text:
                    progress_text = (f'Uploading {os.path.basename(filename)}...'
                                     if event.payload.get('stage') == 'staged' else event.text)
                    yield 1, {'event_type': CommandExecutionEvent.PROGRESS,
                              'text': progress_text, **event.payload}
            elif event.event_type == CommandExecutionEvent.ERROR:
                failure_message = event.text or 'Upload failed'
            elif event.event_type == CommandExecutionEvent.CANCELLED:
                cancelled = True
                if not event.payload.get('terminal'):
                    yield 0, {**event.payload, 'event_type': CommandExecutionEvent.CANCELLED,
                              'text': event.text or 'cancelled', 'failure_reason': 'cancelled'}
            elif event.event_type == CommandExecutionEvent.COMPLETED:
                if cancelled:
                    continue  # The cancellation event already owns the terminal state.
                ok = event.ok is True
                message = (f'File transferred successfully: {os.path.basename(filename)}'
                           if ok else failure_message or 'Upload failed')
                envelope = ResultEnvelope(status='success' if ok else 'error',
                                          message=message).as_payload()
                yield ResultChunk(1 if ok else 0,
                                  render_result_payload(envelope, invocation.output_format), True,
                                  terminal_authoritative=True, event=envelope)


class ScriptBuiltinSupport:
    """
    script builtin: list / view / exec.
    """

    def __init__(self, plan_builder, plan_executor_factory, conn=None, remote_execution_service=None, use_foreground_guard=False, script_catalog_service=None):
        self.plan_builder = plan_builder
        self.plan_executor_factory = plan_executor_factory
        self.conn = conn
        self.remote_execution_service = remote_execution_service
        self.use_foreground_guard = use_foreground_guard
        self.script_catalog_service = script_catalog_service

    def _runtime_config(self):
        from core.protocol.control import ControlDomain, ConfigurationAction
        if not self.use_foreground_guard and self.conn is not None:
            self.conn.runtime.set_foreground_cancel_policy('none')
        status, result = self.remote_execution_service.run_foreground_control(
            self.conn, ControlDomain.CONFIGURATION, ConfigurationAction.GET, {},
            task_type='runtime_config', source='script_options',
            foreground=self.use_foreground_guard)
        if status != 1 or not isinstance(result, dict):
            raise RuntimeError(str(result) or 'Unable to read Configuration')
        config = result.get('data')
        if not isinstance(config, dict) or not isinstance(config.get('items'), list):
            raise RuntimeError('Invalid Configuration GET result')
        return config

    def _platform(self):
        info = getattr(self.conn, 'session_info', None)
        return str(getattr(info, 'os_alias', '') or '')

    def script(self, invocation):
        """Use the Server's parsed invocation; business code never reparses CLI text."""
        subcommand = invocation.action
        args = invocation.arguments
        from core.protocol.result_envelope import ResultEnvelope
        from core.utils.command_output import ResultDataShape, render_result_payload, resolve_presentation
        if subcommand == 'list':
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
            envelope = ResultEnvelope(data=rows).as_payload()
            output_format, layout = resolve_presentation(args, ResultDataShape.LINES)
            text = render_result_payload(envelope, output_format,
                                         view='data', shape=layout, line_field='name')
            yield ResultChunk(1, text, True, terminal_authoritative=True, event=envelope)
            return
        if subcommand == 'view':
            with open(self._resolve_script_path(args['name']), 'rt', encoding='utf-8') as source:
                envelope = ResultEnvelope(message=source.read()).as_payload()
            yield ResultChunk(1, render_result_payload(envelope, invocation.output_format), True,
                              terminal_authoritative=True, event=envelope)
            return
        if subcommand == 'exec':
            yield from self.execute_script_file(args)
            return
        raise ValueError(f'Unsupported script subcommand: {subcommand}')

    def list_scripts(self):
        return [item['path'] for item in self.list_script_catalog()]

    def list_script_catalog(self):
        if self.script_catalog_service is None:
            from server.application.scripts.script_catalog_service import ScriptCatalogService
            self.script_catalog_service = ScriptCatalogService(SCRIPT_PATH)
        return sorted((item for item in self.script_catalog_service.list_scripts()
                       if visible_on_platform(item, self._platform())),
                      key=lambda item: item.get('path', '').lower())

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

    def execute_script_file(self, args: dict):
        modes = {key: args[key] for key in ('execution_mode', 'output_mode')
                 if args[key] is not None}
        payload = prepare_script_control(SCRIPT_PATH, args['name'], args['params'],
                                         config=self._runtime_config(), **modes)
        executor = self.plan_executor_factory()
        for item in executor(self.plan_builder.build_script_plan(payload))():
            yield item


class AliasBuiltinSupport:
    """Alias list/set/unset consume only typed Server Registry invocations."""

    def __init__(self, alias_manager, conn):
        self.alias_manager = alias_manager
        self.conn = conn

    def _get_runtime_platform(self) -> str:
        """Use the AliasManager's canonical Client platform resolution."""
        platform_name = self.alias_manager.get_platform_for_connection(self.conn)
        return platform_name if platform_name in self.alias_manager.get_supported_platforms() else ''

    def _build_resolved_alias_payload(self) -> list[dict]:
        """Effective common definitions plus this Client's platform overrides."""
        runtime_platform = self._get_runtime_platform()
        common = self.alias_manager.list_aliases_for_platform('common', conn=self.conn) or {}
        local = (self.alias_manager.list_aliases_for_platform(runtime_platform, conn=self.conn) or {}
                 if runtime_platform and runtime_platform != 'common' else {})
        merged = {**common, **local}
        return sorted(({
            'platform': runtime_platform if name in local else 'common',
            'alias': name, 'command': command,
        } for name, command in merged.items()),
            key=lambda row: (row['platform'], row['alias']))

    def list_aliases(self):
        """Used by completion; returns current effective names, not a second parser."""
        return self.alias_manager.list_aliases(conn=self.conn)

    def list_resolved_aliases(self) -> list[dict]:
        return self._build_resolved_alias_payload()

    def alias(self, invocation):
        from core.protocol.result_envelope import ResultEnvelope
        from core.utils.command_output import ResultDataShape, render_result_payload, resolve_presentation

        action = invocation.action
        args = invocation.arguments
        try:
            if action == 'list':
                rows = self._build_resolved_alias_payload()
                envelope = ResultEnvelope(message='No aliases configured' if not rows else 'Aliases listed',
                                          data=rows).as_payload()
                view, shape = 'data', ResultDataShape.KEY_VALUE
            elif action in ('set', 'unset'):
                raw_platform = args.get('platform') or 'common'
                platform = self.alias_manager.normalize_platform(raw_platform)
                name = args['name']
                if action == 'set':
                    # `=` is the only Alias-specific grammar. Its RHS is opaque:
                    # preserve nested spaces, quotes, flags and further equals.
                    assignment = args.get('definition') or ''
                    if not assignment.startswith('=') or not assignment[1:].strip():
                        raise ValueError('Expected format: alias set [--platform PLATFORM] name = command')
                    self.alias_manager.add_alias(name, assignment[1:].strip(), platform=platform)
                    message = f'Alias saved [{platform}]: {name}'
                else:
                    self.alias_manager.remove_alias(name, platform=platform)
                    message = f'Alias removed [{platform}]: {name}'
                envelope = ResultEnvelope(message=message).as_payload()
                view, shape = 'message', None
            else:
                raise ValueError(f'Unsupported alias subcommand: {action}')
        except (ValueError, KeyError) as exc:
            envelope = ResultEnvelope(status='error', message=str(exc)).as_payload()
            view, shape = 'message', None

        success = envelope['status'] == 'success'
        if action == 'list' and success:
            output_format, shape = resolve_presentation(args, ResultDataShape.KEY_VALUE)
            output = render_result_payload(envelope, output_format, view='data', shape=shape,
                                           line_field='alias', key_field='alias',
                                           value_field='command', group_field='platform')
        else:
            output = render_result_payload(envelope, invocation.output_format,
                                           view=view, shape=shape)
        yield ResultChunk(1 if success else 0, output,
                          True, terminal_authoritative=True, event=envelope)


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


    def gopin(self, invocation):
        from core.protocol.result_envelope import ResultEnvelope
        from core.utils.command_output import ResultDataShape, render_result_payload, resolve_presentation

        name = str(invocation.arguments.get('command') or '').strip()
        items = self.list_pinned_paths()
        if invocation.action == 'list':
            rows = [{'name': item.get('display_name', ''), 'path': item.get('path', '')}
                    for item in items]
            envelope = ResultEnvelope(data=rows,
                                      message='No saved pinned paths for current host').as_payload()
            fmt, layout = resolve_presentation(invocation.arguments, ResultDataShape.TABLE)
            yield ResultChunk(1, render_result_payload(envelope, fmt,
                              view='data', shape=layout, line_field='name'), True,
                              terminal_authoritative=True, event=envelope)
            return

        if not name:
            envelope = ResultEnvelope(status='error', message='Pinned path name is required').as_payload()
            yield ResultChunk(0, render_result_payload(envelope, invocation.output_format), True,
                              terminal_authoritative=True, event=envelope)
            return

        matched_item = self.pinned_path_store.get_item_by_name(self._get_machine_id(), name)
        if matched_item is None:
            envelope = ResultEnvelope(status='error', message=f'Pinned path not found: {name}').as_payload()
            yield ResultChunk(0, render_result_payload(envelope, invocation.output_format), True,
                              terminal_authoritative=True, event=envelope)
            return

        target_path = str(matched_item.get('path') or '').strip()
        resolved_command = self._build_cd_command(target_path)
        # History retains the original gopin command; downstream cd keeps its stream.
        message = f'gopin {name} -> {resolved_command}'
        yield ResultChunk(1, render_result_payload(ResultEnvelope(message=message).as_payload(),
                                       invocation.output_format), False, terminal_authoritative=True,
                          event={'event_type': 'chunk', 'message': message})

        command_processor = self.command_processor_factory()
        executor = command_processor(resolved_command)
        for item in executor():
            yield item


class HistoryBuiltinSupport:
    """
    history 相关内建命令支持。
    """

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

    def _run_history_item(self, resolved_command: str):
        # Keep the outer invocation (`history run N` or `!N`); the nested
        # execution plan supplies the actual resolved Client command.
        from core.protocol.result_envelope import ResultEnvelope
        from core.utils.command_output import render_result_payload
        message = f'sending command: {resolved_command}'
        yield ResultChunk(1, render_result_payload(ResultEnvelope(message=message).as_payload()),
                          False, terminal_authoritative=True,
                          event={'event_type': 'chunk', 'message': message})

        command_processor = self.command_processor_factory()
        executor = command_processor(resolved_command)
        for item in executor():
            yield item

    def history(self, invocation):
        """History forms are fully parsed by the registry; !N is rewritten upstream."""
        from core.protocol.result_envelope import ResultEnvelope
        from core.utils.command_output import ResultDataShape, render_result_payload, resolve_presentation

        action = invocation.action
        args = invocation.arguments
        output_format = invocation.output_format
        if action == 'list':
            entries = self._get_resolvable_quick_history()
            if args['pinned']:
                entries = [entry for entry in entries if entry.get('is_pinned')]
            rows = [{'index': int(entry['index']), 'command': entry.get('command', ''),
                     'pinned': bool(entry.get('is_pinned'))} for entry in entries]
            envelope = ResultEnvelope(
                message=('No command history available' if not rows else ''),
                data=rows).as_payload()
            output_format, layout = resolve_presentation(args, ResultDataShape.NUMBERED_LIST)
            text = render_result_payload(envelope, output_format, view='data', shape=layout,
                                         line_field='command', footer=('Tip: use history run <index> or !<index> to run a history item quickly'
                                                 if output_format == 'text' else ''))
            yield ResultChunk(1, text, True, terminal_authoritative=True, event=envelope)
            return

        if action == 'clear':
            # Quick Recent is cleared; the independent Pinned store is untouched.
            self.command_history.clear_history_for_connection(self.conn)
            envelope = ResultEnvelope(message='Command history cleared').as_payload()
            yield ResultChunk(1, render_result_payload(envelope, output_format), True,
                              terminal_authoritative=True, event=envelope)
            return

        if action == 'run':
            history_index = args['index']
            try:
                if history_index <= 0:
                    raise ValueError('History index must be positive')
                resolved_command = self._resolve_history_command_by_index(history_index)
            except ValueError as exc:
                envelope = ResultEnvelope(status='error', message=str(exc)).as_payload()
                yield ResultChunk(0, render_result_payload(envelope, output_format), True,
                                  terminal_authoritative=True, event=envelope)
                return
            # The nested Client command can stream; preserve its own result chunks.
            for item in self._run_history_item(resolved_command):
                yield item
            return
        raise ValueError(f'Unsupported history command: {action}')


class RttBuiltinSupport:
    """
    rtt 相关内建命令支持。
    """

    def __init__(self, conn):
        self.conn = conn

    def rtt(self, invocation):
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

        from core.protocol.result_envelope import ResultEnvelope
        from core.utils.command_output import ResultDataShape, render_result_payload, resolve_presentation
        envelope = ResultEnvelope(data=payload).as_payload()
        output, layout = resolve_presentation(invocation.arguments, ResultDataShape.FLAT)
        yield ResultChunk(1, render_result_payload(envelope, output,
                          view='data', shape=layout, width=24), True,
                          terminal_authoritative=True, event=envelope)
