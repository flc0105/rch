from core.protocol.message_types import (
    MSG_TYPE_ACMD,
    MSG_TYPE_CANCEL,
    MSG_TYPE_CANCEL_ACK,
    MSG_TYPE_COMMAND,
    MSG_TYPE_HEARTBEAT,
    MSG_TYPE_HEARTBEAT_ACK,
    MSG_TYPE_RESULT,
    MSG_TYPE_SCRIPT,
    MSG_TYPE_PTY_OPEN,
    MSG_TYPE_PTY_INPUT,
    MSG_TYPE_PTY_RESIZE,
    MSG_TYPE_PTY_CLOSE,
    MSG_TYPE_PTY_OPENED,
    MSG_TYPE_PTY_OUTPUT,
    MSG_TYPE_PTY_CLOSED,
    MSG_TYPE_PTY_ERROR,
    MSG_TYPE_SCREEN_OPEN,
    MSG_TYPE_SCREEN_CONFIG,
    MSG_TYPE_SCREEN_CLOSE,
    MSG_TYPE_SCREEN_INPUT,
    MSG_TYPE_SCREEN_OPENED,
    MSG_TYPE_SCREEN_FRAME,
    MSG_TYPE_SCREEN_CLOSED,
    MSG_TYPE_SCREEN_ERROR,
    MSG_TYPE_SCREEN_INPUT_ERROR,
    MSG_TYPE_CLIPBOARD_GET,
    MSG_TYPE_CLIPBOARD_SET,
    MSG_TYPE_CLIPBOARD_RESULT,
    MSG_TYPE_MONITOR_OPEN,
    MSG_TYPE_MONITOR_CONFIG,
    MSG_TYPE_MONITOR_CLOSE,
    MSG_TYPE_MONITOR_OPENED,
    MSG_TYPE_MONITOR_SNAPSHOT,
    MSG_TYPE_MONITOR_ERROR,
    MSG_TYPE_MONITOR_CLOSED,
    MSG_TYPE_TRANSFER_START,
    MSG_TYPE_TRANSFER_CANCEL,
    MSG_TYPE_TRANSFER_UPDATE,
)


class BaseMessageRouter:
    """
    消息分发基类。
    """

    def __init__(self, connection):
        self.connection = connection

    def dispatch(self, data: dict):
        message_type = data.get('type')

        if message_type == MSG_TYPE_RESULT:
            return self.handle_result_message(data)

        if message_type == MSG_TYPE_COMMAND:
            return self.handle_command_message(data)

        if message_type == MSG_TYPE_SCRIPT:
            return self.handle_script_message(data)

        if message_type == MSG_TYPE_ACMD:
            return self.handle_acmd_message(data)

        if message_type == MSG_TYPE_CANCEL:
            return self.handle_cancel_message(data)
        if message_type == MSG_TYPE_CANCEL_ACK:
            return self.handle_cancel_ack_message(data)

        if message_type == MSG_TYPE_HEARTBEAT:
            return self.handle_heartbeat_message(data)

        if message_type == MSG_TYPE_HEARTBEAT_ACK:
            return self.handle_heartbeat_ack_message(data)


        if message_type == MSG_TYPE_PTY_OPEN:
            return self.handle_pty_open_message(data)

        if message_type == MSG_TYPE_PTY_INPUT:
            return self.handle_pty_input_message(data)

        if message_type == MSG_TYPE_PTY_RESIZE:
            return self.handle_pty_resize_message(data)

        if message_type == MSG_TYPE_PTY_CLOSE:
            return self.handle_pty_close_message(data)

        if message_type == MSG_TYPE_PTY_OPENED:
            return self.handle_pty_opened_message(data)

        if message_type == MSG_TYPE_PTY_OUTPUT:
            return self.handle_pty_output_message(data)

        if message_type == MSG_TYPE_PTY_CLOSED:
            return self.handle_pty_closed_message(data)

        if message_type == MSG_TYPE_PTY_ERROR:
            return self.handle_pty_error_message(data)

        if message_type == MSG_TYPE_SCREEN_OPEN:
            return self.handle_screen_open_message(data)

        if message_type == MSG_TYPE_SCREEN_CONFIG:
            return self.handle_screen_config_message(data)

        if message_type == MSG_TYPE_SCREEN_CLOSE:
            return self.handle_screen_close_message(data)

        if message_type == MSG_TYPE_SCREEN_INPUT:
            return self.handle_screen_input_message(data)

        if message_type == MSG_TYPE_SCREEN_OPENED:
            return self.handle_screen_opened_message(data)

        if message_type == MSG_TYPE_SCREEN_FRAME:
            return self.handle_screen_frame_message(data)

        if message_type == MSG_TYPE_SCREEN_CLOSED:
            return self.handle_screen_closed_message(data)

        if message_type == MSG_TYPE_SCREEN_ERROR:
            return self.handle_screen_error_message(data)

        if message_type == MSG_TYPE_SCREEN_INPUT_ERROR:
            return self.handle_screen_input_error_message(data)

        if message_type == MSG_TYPE_CLIPBOARD_GET:
            return self.handle_clipboard_get_message(data)

        if message_type == MSG_TYPE_CLIPBOARD_SET:
            return self.handle_clipboard_set_message(data)

        if message_type == MSG_TYPE_CLIPBOARD_RESULT:
            return self.handle_clipboard_result_message(data)

        if message_type == MSG_TYPE_MONITOR_OPEN:
            return self.handle_monitor_open_message(data)

        if message_type == MSG_TYPE_MONITOR_CONFIG:
            return self.handle_monitor_config_message(data)

        if message_type == MSG_TYPE_MONITOR_CLOSE:
            return self.handle_monitor_close_message(data)

        if message_type == MSG_TYPE_MONITOR_OPENED:
            return self.handle_monitor_opened_message(data)

        if message_type == MSG_TYPE_MONITOR_SNAPSHOT:
            return self.handle_monitor_snapshot_message(data)

        if message_type == MSG_TYPE_MONITOR_ERROR:
            return self.handle_monitor_error_message(data)

        if message_type == MSG_TYPE_MONITOR_CLOSED:
            return self.handle_monitor_closed_message(data)

        if message_type == MSG_TYPE_TRANSFER_START:
            return self.handle_transfer_start_message(data)

        if message_type == MSG_TYPE_TRANSFER_CANCEL:
            return self.handle_transfer_cancel_message(data)

        if message_type == MSG_TYPE_TRANSFER_UPDATE:
            return self.handle_transfer_update_message(data)

        return self.handle_unknown_message(data)

    def handle_result_message(self, data: dict):
        return None

    def handle_command_message(self, data: dict):
        return None

    def handle_script_message(self, data: dict):
        return None

    def handle_acmd_message(self, data: dict):
        return None

    def handle_cancel_message(self, data: dict):
        return None

    def handle_cancel_ack_message(self, data: dict):
        return None

    def handle_heartbeat_message(self, data: dict):
        return None

    def handle_heartbeat_ack_message(self, data: dict):
        return None


    def handle_pty_open_message(self, data: dict):
        return None

    def handle_pty_input_message(self, data: dict):
        return None

    def handle_pty_resize_message(self, data: dict):
        return None

    def handle_pty_close_message(self, data: dict):
        return None

    def handle_pty_opened_message(self, data: dict):
        return None

    def handle_pty_output_message(self, data: dict):
        return None

    def handle_pty_closed_message(self, data: dict):
        return None

    def handle_pty_error_message(self, data: dict):
        return None

    def handle_screen_open_message(self, data: dict):
        return None

    def handle_screen_config_message(self, data: dict):
        return None

    def handle_screen_close_message(self, data: dict):
        return None

    def handle_screen_input_message(self, data: dict):
        return None

    def handle_screen_opened_message(self, data: dict):
        return None

    def handle_screen_frame_message(self, data: dict):
        return None

    def handle_screen_closed_message(self, data: dict):
        return None

    def handle_screen_error_message(self, data: dict):
        return None

    def handle_screen_input_error_message(self, data: dict):
        return None

    def handle_clipboard_get_message(self, data: dict):
        return None

    def handle_clipboard_set_message(self, data: dict):
        return None

    def handle_clipboard_result_message(self, data: dict):
        return None

    def handle_monitor_open_message(self, data: dict):
        return None

    def handle_monitor_config_message(self, data: dict):
        return None

    def handle_monitor_close_message(self, data: dict):
        return None

    def handle_monitor_opened_message(self, data: dict):
        return None

    def handle_monitor_snapshot_message(self, data: dict):
        return None

    def handle_monitor_error_message(self, data: dict):
        return None

    def handle_monitor_closed_message(self, data: dict):
        return None

    def handle_transfer_start_message(self, data: dict):
        return None

    def handle_transfer_cancel_message(self, data: dict):
        return None

    def handle_transfer_update_message(self, data: dict):
        return None

    def handle_unknown_message(self, data: dict):
        return None
