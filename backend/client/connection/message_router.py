import time

from client.runtime.filesystem.path_resolver import reported_current_directory
from core.protocol.message_router_base import BaseMessageRouter
from core.protocol.screen import SCREEN_DEFAULT_FPS
from core.protocol.message_types import (
    MSG_TYPE_CANCEL_ACK, MSG_TYPE_HEARTBEAT_ACK,
    MSG_TYPE_SCREEN_ERROR, MSG_TYPE_SCREEN_INPUT_ERROR,
    MSG_TYPE_PTY_ERROR,
)


class ClientInboundMessageRouter(BaseMessageRouter):
    """
    Client 侧入站消息路由器。
    """

    def handle_command_message(self, data: dict):
        command_id = data.get('id')
        result = self.connection.runtime.command_executor.execute_command(
            command_id,
            data.get('text'),
            options=data.get('extra') if isinstance(data.get('extra'), dict) else None,
        )
        if result:
            return command_id, *result
        return None

    def handle_acmd_message(self, data: dict):
        command_id = data.get('id')
        result = self.connection.runtime.command_executor.execute_argument_command(
            command_id,
            data.get('extra') or {},
            options=data.get('extra') if isinstance(data.get('extra'), dict) else None,
        )
        if result:
            return command_id, *result
        return None

    def handle_control_message(self, data: dict):
        command_id = data.get('id')
        result = self.connection.runtime.control_dispatcher.execute(
            command_id, data.get('domain'), data.get('action'), data.get('payload'),
            options=data.get('extra') if isinstance(data.get('extra'), dict) else None,
        )
        if result:
            return command_id, *result
        return None

    def handle_completion_message(self, data: dict):
        request_id = data.get('id')
        try:
            result = self.connection.runtime.command_executor.complete_command_completion(data)
            self.connection.send_event(request_id, {
                'event_type': 'completed',
                'status': 'success',
                'message': '',
                'data': result,
            })
        except Exception as exc:
            self.connection.send_event(request_id, {
                'event_type': 'completed',
                'status': 'error',
                'message': str(exc) or 'Completion failed',
            })
        return None

    def handle_cancel_message(self, data: dict):
        target_command_id = data.get('target_id')
        def _report_terminal_state(state):
            self.connection.send({
                'type': MSG_TYPE_CANCEL_ACK,
                'id': data.get('id'),
                'target_id': target_command_id,
                'accepted': True,
                'state': state,
                'cwd': reported_current_directory(),
                'client_ts': time.time(),
            })

        # Completion registration and cancellation must be one atomic operation:
        # a fast exit must not clear the context between those two steps.
        cancel_result = self.connection.runtime.execution.cancel(
            target_command_id, on_completion=_report_terminal_state,
        )
        accepted = bool(cancel_result.get('accepted'))
        message = str(cancel_result.get('message') or '').strip()

        self.connection.send({
            'type': MSG_TYPE_CANCEL_ACK,
            'id': data.get('id'),
            'target_id': target_command_id,
            'accepted': accepted,
            'state': cancel_result.get('state', 'rejected'),
            'message': message,
            'cwd': reported_current_directory(),
            'client_ts': time.time(),
        })
        return None

    def handle_heartbeat_message(self, data: dict):
        self.connection.send({
            'type': MSG_TYPE_HEARTBEAT_ACK,
            'id': data.get('id'),
            'server_ts': data.get('ts'),
            'client_ts': time.time(),
            'cwd': reported_current_directory(),
        })
        return None


    def handle_screen_open_message(self, data: dict):
        if self.connection.runtime.screen_view_manager is None:
            self.connection.send({
                'type': MSG_TYPE_SCREEN_ERROR,
                'screen_session_id': data.get('screen_session_id') or '',
                'message': 'Screen View disabled on Client',
            })
            return None
        self.connection.runtime.screen_view_manager.open_session(
            data.get('screen_session_id') or '',
            fps=data.get('fps') or SCREEN_DEFAULT_FPS,
            quality=data.get('quality') or 60,
        )
        return None

    def handle_screen_config_message(self, data: dict):
        if self.connection.runtime.screen_view_manager is None:
            return None
        self.connection.runtime.screen_view_manager.update_session(
            data.get('screen_session_id') or '',
            fps=data.get('fps'),
            quality=data.get('quality'),
        )
        return None

    def handle_screen_close_message(self, data: dict):
        if self.connection.runtime.screen_view_manager is None:
            return None
        self.connection.runtime.screen_view_manager.close_session(
            data.get('screen_session_id') or '',
        )
        return None

    def handle_screen_input_message(self, data: dict):
        if not self.connection.runtime.features['screen_input']:
            self.connection.send({
                'type': MSG_TYPE_SCREEN_INPUT_ERROR,
                'screen_session_id': data.get('screen_session_id') or '',
                'message': 'Screen Input disabled on Client',
            })
            return None
        self.connection.runtime.screen_view_manager.handle_input(
            data.get('screen_session_id') or '',
            data.get('event') if isinstance(data.get('event'), dict) else {},
        )
        return None

    def handle_pty_open_message(self, data: dict):
        if self.connection.runtime.pty_manager is None:
            self.connection.send({
                'type': MSG_TYPE_PTY_ERROR,
                'pty_session_id': data.get('pty_session_id') or '',
                'message': 'PTY disabled on Client',
            })
            return None
        self.connection.runtime.pty_manager.open_session(
            data.get('pty_session_id') or '',
            shell=data.get('shell') or '',
            cwd=data.get('cwd') or '',
            cols=data.get('cols') or 120,
            rows=data.get('rows') or 32,
        )
        return None

    def handle_pty_input_message(self, data: dict):
        if self.connection.runtime.pty_manager is None:
            return None
        self.connection.runtime.pty_manager.write_input(
            data.get('pty_session_id') or '',
            data.get('data') or '',
        )
        return None

    def handle_pty_resize_message(self, data: dict):
        if self.connection.runtime.pty_manager is None:
            return None
        self.connection.runtime.pty_manager.resize_session(
            data.get('pty_session_id') or '',
            data.get('cols') or 120,
            data.get('rows') or 32,
        )
        return None

    def handle_pty_close_message(self, data: dict):
        if self.connection.runtime.pty_manager is None:
            return None
        self.connection.runtime.pty_manager.close_session(data.get('pty_session_id') or '')
        return None

    def handle_monitor_open_message(self, data: dict):
        self.connection.runtime.device_monitor_manager.open_session(
            data.get('monitor_session_id') or '',
            channels=data.get('channels'),
            intervals=data.get('intervals'),
            options=data.get('options'),
        )
        return None

    def handle_monitor_config_message(self, data: dict):
        self.connection.runtime.device_monitor_manager.update_session(
            data.get('monitor_session_id') or '',
            channels=data.get('channels'),
            intervals=data.get('intervals'),
            options=data.get('options'),
        )
        return None

    def handle_monitor_close_message(self, data: dict):
        self.connection.runtime.device_monitor_manager.close_session(
            data.get('monitor_session_id') or '',
        )
        return None

    def handle_transfer_register_message(self, data: dict):
        self.connection.runtime.transfer_manager.handle_registration(data)
        return None

    def handle_transfer_start_message(self, data: dict):
        self.connection.runtime.transfer_manager.start_transfer(
            data.get('transfer_id') or '',
            data.get('operation') or '',
            payload=data.get('payload') if isinstance(data.get('payload'), dict) else {},
        )
        return None

    def handle_transfer_cancel_message(self, data: dict):
        self.connection.runtime.transfer_manager.cancel_transfer(
            data.get('transfer_id') or '',
        )
        return None

    def handle_heartbeat_ack_message(self, data: dict):
        return None