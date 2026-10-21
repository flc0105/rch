"""Activity record intent follows a command to the *actual* Client dispatch."""
import shlex
import threading
import uuid

from server.application.history.history_record_policy import CommandHistoryRecordPolicy
from server.application.history.quick_history import QuickHistoryRecordPolicy


class CommandHistoryOrchestrator:
    def __init__(self, history_store):
        self.history_store = history_store
        self.quick_store = history_store.quick_store
        self._pending = {}
        self._lock = threading.RLock()

    def should_record_command(self, command, *, source='', task_type=''):
        return CommandHistoryRecordPolicy.should_record_command(command, source=source, task_type=task_type)

    def begin_execution(self, conn, command, source='cli', should_record=None, task_type='', metadata=None):
        if conn is None or not str(command or '').strip():
            return ''
        metadata = dict(metadata or {})
        # Quick management is Server-only. Replay is different: it is never
        # stored in Quick, but its dispatched Client work belongs in Activity.
        if (QuickHistoryRecordPolicy.is_history_management_command(command)
                and not QuickHistoryRecordPolicy.is_history_replay_command(command)):
            return ''
        allowed = should_record is not False
        record_activity = allowed and self.should_record_command(command, source=source, task_type=task_type)
        record_quick = allowed and QuickHistoryRecordPolicy.should_record(
            command, source=source, task_type=task_type, metadata=metadata)
        if not record_activity and not record_quick:
            return ''
        activity_id = uuid.uuid4().hex
        if record_quick:
            self.quick_store.begin(activity_id, conn, command)
        if not record_activity:
            return activity_id
        origin = {'web': 'web_terminal', 'quick_action': 'web_ui', 'cli': 'cli',
                  'web_api': 'web_api'}.get(source, source or 'cli')
        presentation = 'terminal' if origin in {'web_terminal', 'cli'} else 'none'
        kind, action, target, arguments = 'command', 'invoke', None, {}
        text = str(command).strip()
        if metadata.get('quick_action'):
            kind = 'alias'
            origin = 'web_ui'
            target = str(metadata.get('quick_action_alias') or '').strip() or None
            text = str(metadata.get('quick_action_display_command') or text)
            presentation = str(metadata.get('quick_action_presentation') or 'dialog')
            arguments = {'values': metadata.get('quick_action_arguments') or []}
        elif metadata.get('script_run'):
            kind, action, origin = 'script', 'run', 'web_ui'
            target = metadata.get('script_run_name') or None
            text = str(target or text)
            arguments = dict(metadata.get('script_run_arguments') or {})
            presentation = str(metadata.get('script_run_presentation') or 'dialog')
        else:
            # Raw script exec / script run is identified by its *real dispatch type*,
            # not by guessing whether its text looks like a shell command.
            if source == 'web':
                presentation = 'terminal'
            elif source == 'cli':
                presentation = 'terminal'
        invocation = {'input': text, 'arguments': arguments}
        if target:
            invocation['target'] = target
        with self._lock:
            self._pending[activity_id] = {
                'conn': conn, 'kind': kind, 'action': action, 'origin': origin,
                'presentation': presentation, 'invocation': invocation,
                'resolved': {}, 'created_at': self.history_store._now_iso(),
            }
        return activity_id

    def begin_remote_files_execution(self, conn, action, arguments, command_name, command=None, *, origin='web_ui'):
        """Prepare one semantic UI file action, without touching Quick History.

        The Client channel confirms dispatch before it is written. A save command
        intentionally omits its encoded content from the durable resolved data.
        """
        if conn is None:
            return ''
        activity_id = uuid.uuid4().hex
        args = dict(arguments)
        invocation = {'arguments': args}
        # Only actual UI action names belong in the user-facing invocation.
        resolved = {'command_type': 'command', 'command_name': command_name}
        if command is not None:
            resolved['command'] = command
        with self._lock:
            self._pending[activity_id] = {
                'conn': conn, 'kind': 'remote_files', 'action': action,
                'origin': origin, 'presentation': 'none',
                'invocation': invocation, 'resolved': resolved,
                'created_at': self.history_store._now_iso(),
            }
        return activity_id

    def begin_external_tool_execution(self, conn, action, arguments, command_name, *, origin='web_api'):
        """Web Manager intent only; the Client command channel confirms dispatch.

        Never store the encoded lifecycle payload, runtime configuration or parameters.
        """
        if conn is None:
            return ''
        activity_id = uuid.uuid4().hex
        with self._lock:
            self._pending[activity_id] = {
                'conn': conn, 'kind': 'external_tool', 'action': action,
                'origin': origin, 'presentation': 'none',
                'invocation': {'arguments': dict(arguments)},
                'resolved': {'command_type': 'command', 'command_name': command_name},
                'created_at': self.history_store._now_iso(),
            }
        return activity_id

    def describe_plan(self, activity_id, plan):
        if not activity_id or not isinstance(plan, dict):
            return
        with self._lock:
            pending = self._pending.get(activity_id)
            if not pending:
                return
            kind = pending['kind']
            command_type = str(plan.get('command_type') or 'command')
            alias_name = str(plan.get('alias_name') or '').strip()
            if command_type == 'script' and kind != 'alias':
                kind = 'script'
                pending['action'] = 'run'
                if not pending['invocation'].get('target'):
                    # Terminal `script exec <path> <args>` / `script run <encoded>`.
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
                kind = 'alias'
                pending['invocation'].setdefault('target', alias_name)
            pending['kind'] = kind
            # Script content is never copied into Activity; the real transport
            # type and script identity describe the execution without leaking source.
            pending['resolved'] = {'command_type': command_type}
            if command_type != 'script':
                pending['resolved']['command'] = str(plan.get('command') or '')

    def confirm_dispatch(self, conn, activity_id, command, command_type='command'):
        if not activity_id:
            return
        with self._lock:
            pending = self._pending.pop(activity_id, None)
        if not pending:
            return
        if pending['conn'] is not conn:
            return
        if not pending['resolved']:
            pending['resolved'] = {'command_type': command_type}
            if command_type != 'script':
                pending['resolved']['command'] = command
        if command_type == 'script':
            pending['resolved'].pop('command', None)
        self.history_store.write_service.create_activity_for_dispatch(conn, activity_id, pending)

    def claim_upload_intent(self, conn, entry_id):
        """The actual upload transfer owns Activity; keep Quick pending for finalization."""
        with self._lock:
            pending = self._pending.get(entry_id)
            if pending and pending['conn'] is conn and str(pending['invocation'].get('input') or '').startswith('upload '):
                self._pending.pop(entry_id, None)
                return (pending['origin'], pending['invocation']['input'])
        return None

    def discard_execution(self, conn, entry_id):
        self.quick_store.discard(entry_id)
        with self._lock:
            return self._pending.pop(entry_id, None) is not None

    def append_output(self, conn, entry_id, status, text, eof=0):
        self.history_store.append_output_for_connection(conn, entry_id, status, text, eof)

    def update_execution_status(self, conn, entry_id, status):
        if entry_id:
            self.history_store.update_entry_status_for_connection(conn, entry_id, status)

    def finalize_execution(self, conn, entry_id, ok, cwd_end='', status=''):
        with self._lock:
            self._pending.pop(entry_id, None)
        if not entry_id:
            return
        final_status = status or ('success' if ok else 'error')
        # Quick status is saved regardless of whether an Activity was dispatched.
        self.quick_store.finish(entry_id, final_status)
        self.history_store.update_entry_status_for_connection(conn, entry_id, final_status, cwd_end=cwd_end)

    def bind_command_entry(self, conn, command_id, entry_id):
        if conn is None or not command_id or not entry_id:
            return
        try:
            conn.bind_history_entry(command_id, entry_id)
        except Exception:
            pass

    def get_bound_entry_id(self, conn, command_id):
        try:
            return conn.get_history_entry_id(command_id)
        except Exception:
            return ''

    def clear_command_entry(self, conn, command_id):
        try:
            conn.clear_history_entry(command_id)
        except Exception:
            pass

    def bind_uploaded_artifact(self, conn, source_command_id, artifact):
        if conn is None or source_command_id is None or not isinstance(artifact, dict) or not artifact:
            return False
        entry_id = self.get_bound_entry_id(conn, source_command_id)
        if not entry_id:
            return False
        self.history_store.append_file_for_connection(conn, entry_id, artifact)
        return True
