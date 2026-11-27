class WebTerminalApi:
    def __init__(self, pty_session_service):
        self.pty_session_service = pty_session_service

    def open_pty_session(self, client_id: str, *, cols: int = 120, rows: int = 32, shell: str = '', cwd: str = '') -> dict:
        return self.pty_session_service.create_session(client_id, cols=cols, rows=rows, shell=shell, cwd=cwd)

    def send_pty_input(self, pty_session_id: str, data: str) -> dict:
        return self.pty_session_service.write_input(pty_session_id, data)

    def resize_pty_session(self, pty_session_id: str, cols: int, rows: int) -> dict:
        return self.pty_session_service.resize_session(pty_session_id, cols, rows)

    def close_pty_session(self, pty_session_id: str, *, user_initiated=True, reason='') -> dict:
        return self.pty_session_service.close_session(pty_session_id, user_initiated=user_initiated, reason=reason)

    def poll_pty_session(self, pty_session_id: str, after_seq: int = 0) -> dict:
        return self.pty_session_service.get_updates(pty_session_id, after_seq=after_seq)

    def get_pty_ws_info(self, pty_session_id: str) -> dict:
        return self.pty_session_service.get_ws_info(pty_session_id)
