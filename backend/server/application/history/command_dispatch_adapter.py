"""Command dispatch signals and declarative application-operation bindings."""
import contextvars
import functools
import inspect
import logging
import json
import shlex
import uuid

from core.protocol.job_control import validate_job_control_result
from core.protocol.structured_arg_codec import decode_structured_arg
from server.application.history.activity_definitions import (
    ActivityAction, ActivityKind, ActivityOperation, JOB_ACTIVITY_ACTIONS,
)
from server.application.history.history_record_policy import CommandHistoryRecordPolicy
from server.application.history.activity_bindings import xt_cli_mutation
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
            presentation = 'none'
        if record_activity:
            operation = ((xt_cli_mutation(text, origin=origin, presentation=presentation)
                          if kind == ActivityKind.COMMAND else None)
                         or ActivityOperation(kind, action, arguments, origin, presentation, text, target))
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
            if (row and row['kind'] != ActivityKind.EXTERNAL_TOOL
                    and not str(command).startswith('external_tool_exec ')):
                self.coordinator.drop(activity_id)
            return

        def update(pending):
            if pending['kind'] == ActivityKind.EXTERNAL_TOOL:
                return
            kind = pending['kind']
            command_type = str(plan.get('command_type') or 'command')
            alias_name = str(plan.get('alias_name') or '').strip()
            if ((command_type == 'control' and plan.get('domain') == 'script')
                    and kind != ActivityKind.ALIAS):
                kind = ActivityKind.SCRIPT
                pending['action'] = ActivityAction.RUN
                request = plan.get('payload') or {}
                pending['invocation']['target'] = request.get('script_name', '')
                pending['invocation']['arguments'] = request.get('params', {})
            elif alias_name:
                kind = ActivityKind.ALIAS
                pending['invocation'].setdefault('target', alias_name)
            pending['kind'] = kind
            pending['resolved'] = {'command_type': command_type}
            if command_type == 'control' and plan.get('domain') == 'script':
                pending['resolved'].update({key: plan['payload'][key] for key in ('execution_mode', 'output_mode') if key in plan['payload']})
            else:
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

    def dispatch(self, conn, entry_id, command, command_type, *, payload=None, domain='', action=''):
        entry_id = entry_id or self.scoped_entry(conn)
        if not entry_id:
            return ''
        if command_type == 'control' and domain == 'script':
            def record_modes(pending):
                pending['resolved'].update({key: payload[key] for key in ('execution_mode', 'output_mode') if key in payload})
            self.coordinator.mutate_pending(conn, entry_id, record_modes)
        if command_type == 'control' and domain == 'job':
            request = payload if isinstance(payload, dict) else {}
            job_action = JOB_ACTIVITY_ACTIONS.get(action)
            if job_action:
                args = {key: str(request[key]) for key in ('job_name', 'job_key', 'execution_mode')
                        if key in request}
                def promote(pending):
                    pending['kind'] = ActivityKind.BACKGROUND_JOB
                    pending['action'] = job_action
                    pending['resolved'] = {'command_type': 'control'}
                    # Terminal input remains the original user command. Web callers
                    # already provided their structured arguments when preparing.
                    if not pending['invocation'].get('input') and not pending['invocation'].get('arguments'):
                        pending['invocation']['arguments'] = args
                self.coordinator.mutate_pending(conn, entry_id, promote)
            else:
                return entry_id
        if CommandHistoryRecordPolicy.is_internal_external_tool_command(command):
            row = self.coordinator.pending(conn, entry_id)
            if row is None:
                return entry_id
            if (row['kind'] == ActivityKind.EXTERNAL_TOOL
                    and str(row['invocation'].get('input') or '').lower().startswith('xt ')
                    and row['action'] != 'run_exec'):
                mutation_command = {
                    'install_package': 'external_tool_install',
                    'uninstall_package': 'external_tool_uninstall',
                    'create_instance': 'external_tool_instance_create',
                    'start_instance': 'external_tool_start',
                    'stop_instance': 'external_tool_stop',
                    'restart_instance': 'external_tool_stop',
                }.get(row['action'])
                if str(command).split(None, 1)[0] != mutation_command:
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

    def observe_result(self, conn, entry_id, command_type, command, rows, *, payload=None, domain='', action=''):
        """Read a completed command result once; preserve the iterator and raw Client output."""
        if command_type != 'control' or domain != 'job':
            yield from rows
            return
        last = None
        for item in rows:
            last = item
            yield item
        if last is None or not entry_id:
            return
        try:
            if action not in JOB_ACTIVITY_ACTIONS:
                return
            result = validate_job_control_result(last[1], action)
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
