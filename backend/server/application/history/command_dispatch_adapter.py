"""Command dispatch signals and declarative application-operation bindings."""
import contextvars
import functools
import inspect
import logging
import uuid

from core.protocol.control import ControlDomain, ScriptAction
from server.application.history.control_activity import should_record
from server.application.command.command_types import COMMAND_TYPE_CONTROL
from server.application.history.activity_definitions import (
    ActivityAction, ActivityKind, ActivityOperation, operation_summary,
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

    def __init__(self, coordinator, connection_lookup):
        self.coordinator = coordinator
        self.connection_lookup = connection_lookup
        self.lifecycle_adapter = None
        self._scope = contextvars.ContextVar('rch_activity_command_scope', default=None)
        self._dispatch_entry = contextvars.ContextVar('rch_activity_dispatch_entry', default=None)

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
        if entry_id and operation.kind in tuple(ControlDomain):
            self.coordinator.drop(entry_id)
        elif entry_id:
            try:
                status = operation_status(operation, result)
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
        text = str(command)
        origin = self._origin_map.get(source, source or 'cli')
        presentation = 'terminal' if origin in {'web_terminal', 'cli', 'rch_cli'} else 'none'
        kind, action, target, arguments = ActivityKind.COMMAND, ActivityAction.INVOKE, '', {}
        if metadata.get('quick_action'):
            kind, origin = ActivityKind.ALIAS, 'web_ui'
            target = str(metadata.get('quick_action_alias') or '').strip()
            text = ''
            presentation = str(metadata.get('quick_action_presentation') or 'dialog')
            arguments = {'values': metadata.get('quick_action_arguments') or []}
        elif metadata.get('script_run'):
            kind, action, origin = ControlDomain.SCRIPT, ScriptAction.RUN, 'web_ui'
            target = str(metadata.get('script_run_name') or '')
            text = ''
            arguments = dict(metadata.get('script_run_arguments') or {})
            presentation = 'none'
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
        def update(pending):
            if pending['kind'] == ActivityKind.EXTERNAL_TOOL:
                return
            alias_name = str(plan.get('alias_name') or '').strip()
            if alias_name:
                pending['kind'] = ActivityKind.ALIAS
                pending['summary'] = alias_name
        self.coordinator.mutate_pending(conn, activity_id, update)

    def suppress_query(self, conn, activity_id):
        self.coordinator.drop(activity_id)

    def send_command(self, conn, command, *, entry_id='', **kwargs):
        # Explicit intent belongs to the application dispatch scope, not the session.
        token = self._dispatch_entry.set((conn, entry_id))
        try:
            return conn.send_command(command, **kwargs)
        finally:
            self._dispatch_entry.reset(token)

    def dispatch_request(self, conn, data, send):
        scoped = self._dispatch_entry.get()
        entry_id = scoped[1] if scoped is not None and scoped[0] is conn else ''
        command_id = data['id']
        try:
            entry_id = self.prepare_dispatch(conn, entry_id, data)
        except Exception:
            logger.exception('Unable to prepare request Activity')
            entry_id = ''
        self.coordinator.bind_command_entry(conn, command_id, entry_id)
        try:
            rows = send()
        except BaseException:
            self.coordinator.clear_command_entry(conn, command_id)
            if entry_id:
                self.coordinator.drop(entry_id)
            raise
        entry_id = self.dispatch(conn, entry_id, data)

        def observed():
            try:
                yield from self.observe_result(conn, entry_id, data, rows)
            finally:
                try:
                    close = getattr(rows, 'close', None)
                    if close is not None:
                        close()
                finally:
                    self.coordinator.clear_command_entry(conn, command_id)
        return observed()

    def prepare_dispatch(self, conn, entry_id, data):
        if data['type'] != COMMAND_TYPE_CONTROL:
            return entry_id or self.scoped_entry(conn)
        domain, action = data['domain'], data['action']
        candidate = entry_id or self.scoped_entry(conn)
        previous = self.coordinator.pending(conn, candidate) if candidate else None
        # A nested request cannot consume another operation's prepared intent.
        if previous and not ((entry_id and previous['kind'] in (ActivityKind.COMMAND, ActivityKind.ALIAS))
                             or (previous['kind'], previous['action']) == (domain, action)):
            previous, candidate = None, ''
        if not should_record(domain, action):
            if entry_id and previous and (previous['kind'], previous['action']) == (domain, action):
                self.coordinator.drop(candidate)
            return ''
        if not previous:
            candidate = ''
        operation = ActivityOperation(domain, action, data['payload'],
                                      previous['origin'] if previous else 'web_ui',
                                      previous['presentation'] if previous else 'none')
        prepared = self.coordinator.prepare(conn, operation, entry_id=candidate)
        if previous and (previous['kind'], previous['action']) == (domain, action):
            self.coordinator.mutate_pending(conn, prepared, lambda row: row.update(summary=previous['summary']))
        return prepared

    def dispatch(self, conn, entry_id, data):
        if not entry_id:
            return ''
        command = data.get('text', '')
        try:
            pending = self.coordinator.pending(conn, entry_id)
            if pending and pending['kind'] == ActivityKind.COMMAND:
                self.coordinator.mutate_pending(conn, entry_id, lambda row: row.update(
                    summary=operation_summary(ActivityKind.COMMAND, row['action'], {}, command)))
            if self.coordinator.dispatch(conn, entry_id, data=data):
                return entry_id
        except Exception:
            logger.exception('Unable to confirm dispatched command Activity')
        return ''

    def observe_result(self, conn, entry_id, data, rows):
        finalize_on_completion = data['type'] == COMMAND_TYPE_CONTROL
        if not entry_id:
            yield from rows
            return
        final = None
        try:
            for item in rows:
                result = item.event
                outcome = item.terminal_status
                if outcome is not None:
                    final = outcome
                try:
                    self.coordinator.append_client_result(conn, entry_id, result)
                    if outcome is not None:
                        self.coordinator.add_references(conn, entry_id, result.get('references'))
                        if finalize_on_completion:
                            self.coordinator.finish(conn, entry_id, item.succeeded, status=outcome)
                except Exception:
                    logger.exception('Unable to record request result')
                yield item
            if finalize_on_completion and final is None:
                self._interrupt_request(conn, entry_id, 'interrupted')
        except BaseException as exc:
            if finalize_on_completion and final is None:
                final = ('timed_out' if isinstance(exc, TimeoutError) else
                         'interrupted' if isinstance(exc, (ConnectionError, EOFError, GeneratorExit)) else 'error')
                self._interrupt_request(conn, entry_id, final)
            raise

    def _interrupt_request(self, conn, entry_id, status):
        try:
            self.coordinator.finish(conn, entry_id, False, status=status)
        except Exception:
            logger.exception('Unable to finalize interrupted request Activity')


def operation_status(operation, result):
    """Evaluate only the safe returned operation result, never encoded Client command payloads."""
    if operation.kind == ActivityKind.EXTERNAL_TOOL:
        if not isinstance(result, dict):
            return 'error'
        action = operation.action
        if action == 'run_oneshot' and result.get('timed_out') is True:
            return 'timed_out'
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
        return 'success' if checks.get(action, False) else 'error'
    return 'success'
