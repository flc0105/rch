class ClientSessionContext:
    """
    客户端会话上下文。

    职责：
    - 保存不属于 transport 本体、也不属于 runtime 队列的数据
    - 保存上层（CLI / Web / history / artifact）注入到会话中的上下文能力
    - 保存会话心跳/存活状态信息

    当前承载：
    - is_interactive
    - command_history
    - artifact_service
    - script_grant_service
    - on_unexpected_message
    - on_heartbeat_updated
    - connected_at
    - disconnected_at
    - last_seen_at
    - last_heartbeat_sent_at
    - last_heartbeat_ack_at
    - last_rtt_ms
    - last_heartbeat_id
    """

    def __init__(self):
        self.is_interactive = False
        self.command_history = None
        self.command_history_orchestrator = None
        self.artifact_service = None
        self.script_grant_service = None
        self.on_unexpected_message = None
        self.on_heartbeat_updated = None
        self.on_pty_opened = None
        self.on_pty_output = None
        self.on_pty_closed = None
        self.on_pty_error = None
        self.on_screen_opened = None
        self.on_screen_frame = None
        self.on_screen_closed = None
        self.on_screen_error = None
        self.on_screen_input_error = None
        self.on_clipboard_result = None
        self.on_monitor_opened = None
        self.on_monitor_snapshot = None
        self.on_monitor_error = None
        self.on_monitor_closed = None
        self.on_transfer_update = None

        self.connected_at = ''
        self.disconnected_at = ''
        self.server_disconnect_request = None
        self.client_session_end = None
        self.last_seen_at = ''
        self.last_heartbeat_sent_at = ''
        self.last_heartbeat_ack_at = ''
        self.last_rtt_ms = None
        self.last_heartbeat_id = None









