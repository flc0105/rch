from core.protocol.message_types import MSG_TYPE_COMMAND, MSG_TYPE_CANCEL, MSG_TYPE_SCRIPT
from importlib import import_module
from client.commands.runtime.catalog import CommandCatalog
from client.commands.common.commands import CommonCommands
from server.application.auth.script_grant_service import (
    SCRIPT_GRANT_REQUEST_KEY,
    SCRIPT_GRANT_TOKEN_KEY,
)


class ClientSessionCommandChannel:
    """
    客户端会话命令通道。

    职责：
    - 生成消息 id
    - 下发远程命令
    - 等待对应结果返回
    """

    def __init__(self, session):
        self.session = session
        self._message_id_counter = 0

    def generate_message_id(self) -> int:
        self._message_id_counter += 1
        return self._message_id_counter

    def _build_script_grant_extra(self, command_id: int, extra: dict) -> dict:
        prepared_extra = dict(extra or {})
        grant_request = prepared_extra.pop(SCRIPT_GRANT_REQUEST_KEY, None)
        if not isinstance(grant_request, dict) or not grant_request:
            return prepared_extra

        script_grant_service = getattr(self.session.context, 'script_grant_service', None)
        if script_grant_service is None:
            return prepared_extra

        grant_payload = script_grant_service.issue_script_grant(
            session=self.session,
            command_id=command_id,
            grant_request=grant_request,
        )
        if grant_payload:
            prepared_extra[SCRIPT_GRANT_TOKEN_KEY] = grant_payload
        return prepared_extra

    def build_command_payload(self, command: str, command_type: str = MSG_TYPE_COMMAND, extra=None) -> dict:
        data = {
            'type': command_type,
            'id': self.generate_message_id(),
            'text': command,
        }
        # Only explicitly interactive Client commands receive task-bound grants.
        # Other Client and shell commands are untouched.
        if command_type == MSG_TYPE_COMMAND:
            import shlex
            try:
                parts = shlex.split(command or '')
            except ValueError:
                parts = []
            # Resolve grants from the Server's trusted command definitions,
            # never from a Client-supplied command manifest.
            method = getattr(CommonCommands, parts[0], None) if parts else None
            if parts and (method is None or not hasattr(method, 'help')):
                # Platform-only commands also carry trusted method annotations.
                session_info = getattr(self.session, 'session_info', None)
                os_alias = str(getattr(session_info, 'os_alias', '') or '').lower()
                platform_info = CommandCatalog.PLATFORM_COMMAND_MODULES.get(os_alias)
                if platform_info:
                    module_name, class_name = platform_info
                    try:
                        command_class = getattr(import_module(module_name), class_name)
                    except (ImportError, AttributeError):
                        method = None  # Unavailable platform module: never issue an unverified grant.
                    else:
                        method = getattr(command_class, parts[0], None)
            grants = getattr(method, 'api_grants', ()) if callable(method) and hasattr(method, 'help') else ()
            if grants:
                extra = self._build_script_grant_extra(data['id'], {
                    **(extra if isinstance(extra, dict) else {}),
                    SCRIPT_GRANT_REQUEST_KEY: {
                        'script_name': f'client-command:{parts[0]}',
                        'api_grants': list(grants),
                        'ttl_seconds': 300,
                    },
                })
        if extra:
            if command_type == MSG_TYPE_SCRIPT and isinstance(extra, dict):
                extra = self._build_script_grant_extra(data.get('id'), extra)
            data['extra'] = extra
        return data

    def build_cancel_payload(self, target_command_id: int) -> dict:
        return {
            'type': MSG_TYPE_CANCEL,
            'id': self.generate_message_id(),
            'target_id': target_command_id,
        }

    def send_command(self, command: str, type=MSG_TYPE_COMMAND, extra=None, history_entry_id: str = ''):
        data = self.build_command_payload(command, type, extra)

        history_orchestrator = getattr(self.session.context, 'command_history_orchestrator', None)

        bound_task = self.session.runtime.bind_command_execution(
            data.get('id'),
            session=self.session,
            history_entry_id=history_entry_id,
            history_orchestrator=history_orchestrator,
        )
        self.session.send(data)
        # Persist only after the transport has accepted an actual Client command.
        # This is deliberately restricted to explicitly prepared Activity intents:
        # internal requests and pure Server builtins never create Activity.
        if history_orchestrator is not None:
            history_orchestrator.confirm_dispatch(
                self.session, history_entry_id, command, command_type=type,
            )

        if bound_task and bound_task.get('cancel_requested'):
            self.send_cancel(data.get('id'))

        return self.wait_for_result(data.get('id'), command if type == MSG_TYPE_COMMAND else None)

    def send_cancel(self, target_command_id: int):
        data = self.build_cancel_payload(target_command_id)
        self.session.send(data)
        return data

    def wait_for_result(self, command_id: int, command: str = ''):
        yield from self.session.runtime.wait_for_result(self.session, command_id, command)









