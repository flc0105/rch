import os
import time

from core.protocol.message_router_base import BaseMessageRouter
from core.protocol.screen import SCREEN_DEFAULT_FPS
from core.protocol.message_types import MSG_TYPE_CANCEL_ACK, MSG_TYPE_HEARTBEAT_ACK


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

    def handle_script_message(self, data: dict):
        command_id = data.get('id')
        result = self.connection.runtime.command_executor.execute_script_command(
            command_id,
            data.get('text') or '',
            kwargs=data.get('extra'),
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

    def handle_cancel_message(self, data: dict):
        target_command_id = data.get('target_id')
        cancel_result = self.connection.runtime.command_executor.cancel_command(target_command_id)
        accepted = bool(cancel_result.get('accepted'))
        message = str(cancel_result.get('message') or '').strip()

        if not accepted and target_command_id:
            self.connection.send_result(target_command_id, 0, message or 'Command does not support cancellation', 0)

        self.connection.send({
            'type': MSG_TYPE_CANCEL_ACK,
            'id': data.get('id'),
            'target_id': target_command_id,
            'accepted': accepted,
            'message': message,
            'cwd': os.getcwd(),
            'client_ts': time.time(),
        })
        return None

    def handle_heartbeat_message(self, data: dict):
        self.connection.send({
            'type': MSG_TYPE_HEARTBEAT_ACK,
            'id': data.get('id'),
            'server_ts': data.get('ts'),
            'client_ts': time.time(),
            'cwd': os.getcwd(),
        })
        return None


    def handle_screen_open_message(self, data: dict):
        self.connection.runtime.screen_view_manager.open_session(
            data.get('screen_session_id') or '',
            fps=data.get('fps') or SCREEN_DEFAULT_FPS,
            quality=data.get('quality') or 60,
        )
        return None

    def handle_screen_config_message(self, data: dict):
        self.connection.runtime.screen_view_manager.update_session(
            data.get('screen_session_id') or '',
            fps=data.get('fps'),
            quality=data.get('quality'),
        )
        return None

    def handle_screen_close_message(self, data: dict):
        self.connection.runtime.screen_view_manager.close_session(
            data.get('screen_session_id') or '',
        )
        return None

    def handle_screen_input_message(self, data: dict):
        self.connection.runtime.screen_view_manager.handle_input(
            data.get('screen_session_id') or '',
            data.get('event') if isinstance(data.get('event'), dict) else {},
        )
        return None

    def handle_clipboard_get_message(self, data: dict):
        # 显式读取目标机器当前剪贴板，不做自动同步。
        self.connection.runtime.clipboard_manager.handle_get(
            data.get('clipboard_request_id') or '',
            mode=data.get('mode') or 'content',
        )
        return None

    def handle_clipboard_set_message(self, data: dict):
        # 文本、图片、文件统一交给 ClipboardManager 落到原生剪贴板。
        self.connection.runtime.clipboard_manager.handle_set(
            data.get('clipboard_request_id') or '',
            data.get('payload') if isinstance(data.get('payload'), dict) else {},
        )
        return None

    def handle_pty_open_message(self, data: dict):
        self.connection.runtime.pty_manager.open_session(
            data.get('pty_session_id') or '',
            shell=data.get('shell') or '',
            cwd=data.get('cwd') or '',
            cols=data.get('cols') or 120,
            rows=data.get('rows') or 32,
        )
        return None

    def handle_pty_input_message(self, data: dict):
        self.connection.runtime.pty_manager.write_input(
            data.get('pty_session_id') or '',
            data.get('data') or '',
        )
        return None

    def handle_pty_resize_message(self, data: dict):
        self.connection.runtime.pty_manager.resize_session(
            data.get('pty_session_id') or '',
            data.get('cols') or 120,
            data.get('rows') or 32,
        )
        return None

    def handle_pty_close_message(self, data: dict):
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