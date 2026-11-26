"""Independent Client session lifecycle actions."""
import os

from core.protocol.control import SessionAction


class SessionControl:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, scope, action, payload):
        if action == SessionAction.GET_REVISION_FILES:
            from client.config.config import CLIENT_SOURCE_REVISION, CLIENT_SOURCE_REVISION_FILES
            from core.client_revision import build_client_revision_manifest
            if CLIENT_SOURCE_REVISION:
                files = dict(CLIENT_SOURCE_REVISION_FILES or {})
            else:
                from client.connection.handshake import get_revision_file_stats_at_start
                original = get_revision_file_stats_at_start()
                current = {} if original is not None else None
                files = build_client_revision_manifest(include_files=True, file_stats=current).get('files') or {}
                changed = []
                if current is not None:
                    for path in sorted(set(original) | set(current)):
                        if original.get(path) == current.get(path):
                            continue
                        change = ('added' if path not in original else
                                  'removed' if path not in current else 'modified')
                        changed.append({'path': path, 'change': change})
                return 1, {'files': files, 'changed_since_start': changed}
            return 1, {'files': files}
        if action == SessionAction.GET_VARIABLE_MANIFEST:
            return 1, {'items': self.connection.runtime.command_executor.get_command_variable_manifest()}
        if action != SessionAction.DISCONNECT:
            return 0, 'Unsupported session Control action'
        scope._checkpoint()
        # This operation intentionally ends the process, like kill_instance.
        # The Server has already recorded the disconnect intent before sending.
        try:
            self.connection.report_session_end('server_requested_disconnect', command='kill_instance')
        finally:
            try:
                # An intentional Server disconnect must stop the process-death
                # supervisor before os._exit; otherwise it respawns this Client.
                recovery_manager = getattr(self.connection, 'process_recovery_watchdog_manager', None)
                try:
                    if recovery_manager is not None:
                        recovery_manager.stop()
                finally:
                    worker_manager = getattr(self.connection, 'watchdog_manager', None)
                    if worker_manager is not None:
                        worker_manager.stop()
            finally:
                try:
                    self.connection.close()
                finally:
                    os._exit(0)
