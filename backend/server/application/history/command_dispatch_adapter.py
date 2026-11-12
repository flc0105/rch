"""Command dispatch signals and declarative application-operation bindings."""
import contextvars
import functools
import inspect
import logging
import json
import shlex
import uuid

from core.utils.job_control_result import decode_job_control_result
from core.protocol.structured_arg_codec import decode_structured_arg
from server.application.history.activity_definitions import (
    ActivityAction, ActivityKind, ActivityOperation,
)
from server.application.history.history_record_policy import CommandHistoryRecordPolicy
from server.application.history.quick_history import QuickHistoryRecordPolicy

logger = logging.getLogger(__name__)


class _OperationFacade:
    """Application composition wrapper; the underlying service remains unaware of Activity."""

    def __init__(self, target, adapter, bindings):
        self._target = target
        self._adapter = adapter
        self._bindings = bindings

    def __getattr__(self, name):
        original = getattr(self._target, name)
        factory = self._bindings.get(name)
        if factory is None:
            return original

        @functools.wraps(original)
        def wrapped(*args, **kwargs):
            signature = inspect.signature(original)
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            values = bound.arguments
            try:
                operation = factory(values)
            except (ValueError, TypeError, KeyError):
                # Let the domain service validate its own request and error contract.
                return original(*args, **kwargs)
            if operation is None:
                return original(*args, **kwargs)
            client_id = values.get('client_id')
            return self._adapter.execute_operation(client_id, operation, lambda: original(*args, **kwargs))
        return wrapped


class CommandDispatchAdapter:
    """Only command adapter: terminal/CLI and explicitly declared Web mutations."""

    _origin_map = {'web': 'web_terminal', 'quick_action': 'web_ui', 'cli': 'cli',
                   'web_api': 'web_api', 'rch_cli': 'rch_cli'}
    _job_actions = {'start': 'start_job', 'stop': 'stop_job', 'stop_all': 'stop_all_jobs'}

    def __init__(self, coordinator, connection_lookup):
        self.coordinator = coordinator
        self.connection_lookup = connection_lookup
        self.lifecycle_adapter = None
        self._scope = contextvars.ContextVar('rch_activity_command_scope', default=None)

    def bind_lifecycle_adapter(self, adapter):
        self.lifecycle_adapter = adapter

    def instrument(self, target, bindings):
        return _OperationFacade(target, self, bindings)

    def scoped_entry(self, conn):
        item = self._scope.get()
        return item[1] if item is not None and item[0] is conn else ''

    def execute_operation(self, client_id, operation, execute):
        # A business request should still reach its service if connection lookup fails.
        try:
            conn = self.connection_lookup(client_id)
        except Exception:
            return execute()
        try:
            entry_id = self.coordinator.prepare(conn, operation)
        except Exception:
            logger.exception('Unable to prepare command Activity')
            entry_id = ''
        token = self._scope.set((conn, entry_id))
        try:
            result = execute()
        except Exception as exc:
            if entry_id:
                status = ('timed_out' if isinstance(exc, TimeoutError) else
                          'interrupted' if isinstance(exc, ConnectionError) else 'error')
                # Validation failures before Client dispatch never create Activity rows.
                try:
                    self.coordinator.finish(conn, entry_id, False, status=status)
                except Exception:
                    logger.exception('Unable to finalize failed command Activity')
            raise
        finally:
            self._scope.reset(token)
        if entry_id:
            try:
                status, message, details = evaluate_operation(operation, result)
                if details:
                    self.coordinator.details(conn, entry_id, details)
                    if operation.kind == ActivityKind.BACKGROUND_JOB:
                        self.coordinator.job_result(conn, entry_id, details)
                if message:
                    self.coordinator.append_output(conn, entry_id, int(status == 'success'), message)
                self.coordinator.finish(conn, entry_id, status == 'success', status=status)
            except Exception:
                logger.exception('Unable to finalize command Activity')
        return result

    def prepare_command(self, conn, command, source='cli', should_record=None, task_type='', metadata=None):
        if conn is None or not str(command or '').strip():
            return ''
        metadata = dict(metadata or {})
        if (QuickHistoryRecordPolicy.is_history_management_command(command)
                and not QuickHistoryRecordPolicy.is_history_replay_command(command)):
            return ''
        allowed = should_record is not False
        record_activity = allowed and CommandHistoryRecordPolicy.should_record_command(
            command, source=source, task_type=task_type)
        record_quick = allowed and QuickHistoryRecordPolicy.should_record(
            command, source=source, task_type=task_type, metadata=metadata)
        if not record_activity and not record_quick:
            return ''
        text = str(command).strip()
        origin = self._origin_map.get(source, source or 'cli')
        presentation = 'terminal' if origin in {'web_terminal', 'cli', 'rch_cli'} else 'none'
        kind, action, target, arguments = ActivityKind.COMMAND, ActivityAction.INVOKE, '', {}
        if metadata.get('quick_action'):
            kind, origin = ActivityKind.ALIAS, 'web_ui'
            target = str(metadata.get('quick_action_alias') or '').strip()
            text = str(metadata.get('quick_action_display_command') or text)
            presentation = str(metadata.get('quick_action_presentation') or 'dialog')
            arguments = {'values': metadata.get('quick_action_arguments') or []}
        elif metadata.get('script_run'):
            kind, action, origin = ActivityKind.SCRIPT, ActivityAction.RUN, 'web_ui'
            target = str(metadata.get('script_run_name') or '')
            text = target or text
            arguments = dict(metadata.get('script_run_arguments') or {})
            presentation = str(metadata.get('script_run_presentation') or 'dialog')
        if record_activity:
            operation = ActivityOperation(kind, action, arguments, origin, presentation, text, target)
            entry_id = self.coordinator.prepare(conn, operation)
        else:
            entry_id = uuid.uuid4().hex
        if record_quick:
            self.coordinator.quick_store.begin(entry_id, conn, command)
        return entry_id

    def describe_plan(self, conn, activity_id, plan):
        if not activity_id or not isinstance(plan, dict):
            return
        command = plan.get('command')
        if CommandHistoryRecordPolicy.is_internal_external_tool_command(command):
            row = self.coordinator.pending(conn, activity_id)
            if row and row['kind'] != ActivityKind.EXTERNAL_TOOL:
                self.coordinator.drop(activity_id)
            return

        def update(pending):
            if pending['kind'] == ActivityKind.EXTERNAL_TOOL:
                return
            kind = pending['kind']
            command_type = str(plan.get('command_type') or 'command')
            alias_name = str(plan.get('alias_name') or '').strip()
            if command_type == 'script' and kind != ActivityKind.ALIAS:
                kind = ActivityKind.SCRIPT
                pending['action'] = ActivityAction.RUN
                if not pending['invocation'].get('target'):
                    original = str(pending['invocation']['input']).strip()
                    if original.startswith('script exec '):
                        try:
                            parts = shlex.split(original)
                            pending['invocation']['target'] = parts[2]
                            pending['invocation']['arguments'] = {'argv': parts[3:]}
                        except (ValueError, IndexError):
                            pass
                    elif original.startswith('script run '):
                        pending['invocation']['target'] = str((plan.get('extra') or {}).get('__script_name__') or '')
            elif alias_name:
                kind = ActivityKind.ALIAS
                pending['invocation'].setdefault('target', alias_name)
            pending['kind'] = kind
            pending['resolved'] = {'command_type': command_type}
            if command_type != 'script':
                pending['resolved']['command'] = str(command or '')
        self.coordinator.mutate_pending(conn, activity_id, update)

    def promote_external_exec(self, conn, activity_id, target):
        def promote(pending):
            pending['kind'] = ActivityKind.EXTERNAL_TOOL
            pending['action'] = 'run_exec'
            pending['invocation']['arguments'] = {
                'exec_name': str(target.get('exec_name') or ''),
                'package_id': str(target.get('package_id') or ''),
            }
            pending['resolved'] = {'command_type': 'command'}
        self.coordinator.mutate_pending(conn, activity_id, promote)

    def suppress_query(self, conn, activity_id):
        self.coordinator.drop(activity_id)

    def dispatch(self, conn, entry_id, command, command_type):
        entry_id = entry_id or self.scoped_entry(conn)
        # Legacy receive_file is a Transfer, not a second Command Activity.
        # Claim the pending Terminal ID before the command candidate can be persisted.
        if self.lifecycle_adapter is not None and str(command).startswith('receive_file '):
            try:
                payload = decode_structured_arg(str(command).split(None, 1)[1], require_prefix=True)
                if (isinstance(payload, dict) and payload.get('transfer_id')
                        and self.lifecycle_adapter.transfer_command_dispatched(conn, payload['transfer_id'])):
                    return entry_id
            except Exception:
                logger.exception('Unable to track dispatched receive_file transfer')
        if not entry_id:
            return ''
        if command_type == 'job_control':
            try:
                payload = json.loads(command)
            except (ValueError, TypeError):
                payload = {}
            action = self._job_actions.get(payload.get('action'))
            if action:
                args = {key: str(payload[key]) for key in ('job_name', 'job_key', 'execution_mode')
                        if key in payload}
                self.coordinator.prepare(conn, ActivityOperation(
                    ActivityKind.BACKGROUND_JOB, action, args,
                    origin='web_api', resolved={'command_type': 'job_control'}, reuse_origin=True,
                ), entry_id=entry_id)
            else:
                return entry_id
        if CommandHistoryRecordPolicy.is_internal_external_tool_command(command):
            row = self.coordinator.pending(conn, entry_id)
            if row is None:
                return entry_id
            if str(command).startswith('external_tool_exec '):
                try:
                    target = decode_structured_arg(str(command).split(None, 1)[1], require_prefix=True)
                except (ValueError, TypeError, IndexError):
                    return entry_id
                if not isinstance(target, dict):
                    return entry_id
                self.promote_external_exec(conn, entry_id, target)
            elif row['kind'] != ActivityKind.EXTERNAL_TOOL:
                return entry_id
        try:
            self.coordinator.dispatch(conn, entry_id, command=command, command_type=command_type)
        except Exception:
            # The command has already reached Client; Activity storage cannot undo it.
            logger.exception('Unable to confirm dispatched command Activity')
        return entry_id

    def observe_result(self, conn, entry_id, command_type, command, rows):
        """Read a completed command result once; preserve the iterator and raw Client output."""
        if command_type != 'job_control':
            yield from rows
            return
        last = None
        for item in rows:
            last = item
            yield item
        if last is None or not entry_id:
            return
        try:
            action = json.loads(command).get('action')
            if action not in self._job_actions:
                return
            result = decode_job_control_result(last[1], action)
            self.coordinator.job_result(conn, entry_id, result)
        except (ValueError, TypeError, KeyError, IndexError):
            return


def evaluate_operation(operation, result):
    """Evaluate only the safe returned operation result, never encoded Client command payloads."""
    if operation.kind == ActivityKind.EXTERNAL_TOOL:
        if not isinstance(result, dict):
            return 'error', 'External tool operation failed', {}
        action = operation.action
        if action == 'run_oneshot' and result.get('timed_out') is True:
            return 'timed_out', 'External tool operation timed out', {}
        checks = {
            'install_package': result.get('installed') is True,
            'uninstall_package': result.get('installed') is False,
            'start_instance': result.get('running') is True,
            'stop_instance': result.get('running') is False,
            'run_oneshot': result.get('success') is True and result.get('returncode') == 0,
            'clear_package_cache': isinstance(result.get('cache'), dict) and isinstance(result.get('cache_removed'), bool),
            'remove_instance': result.get('removed') is True,
            'clear_instance_logs': result.get('cleared') is True,
        }
        ok = checks.get(action, False)
        noun = operation.arguments.get('package_id') or operation.arguments.get('tool_id') or 'External tool'
        instance = operation.arguments.get('instance_id') or result.get('instance_id')
        summary = f'{action.replace("_", " ").capitalize()}: {noun}'
        if instance:
            summary += f' ({instance})'
        return ('success' if ok else 'error', summary + (' completed' if ok else ' failed'), {})
    if operation.kind == ActivityKind.BACKGROUND_JOB and isinstance(result, dict):
        return 'success', str(result.get('message') or ''), result
    if operation.kind == ActivityKind.REMOTE_FILES:
        if isinstance(result, dict):
            if 'failed' in result and result.get('failed'):
                return 'error', str(result.get('message') or 'Remote file operation failed'), {}
            return 'success', str(result.get('message') or json.dumps(result, ensure_ascii=False)), {}
        return 'success', str(result), {}
    if operation.kind == ActivityKind.PROCESS:
        return 'success', str((result or {}).get('message') or ''), {}
    return 'success', '', {}
