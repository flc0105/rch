from core.protocol.screen import SCREEN_DEFAULT_FPS

class WebScreenViewApi:
    def __init__(self, screen_view_session_service):
        self.screen_view_session_service = screen_view_session_service

    def open_screen_view(self, client_id: str, *, fps: int = SCREEN_DEFAULT_FPS, quality: int = 60) -> dict:
        return self.screen_view_session_service.create_session(client_id, fps=fps, quality=quality)

    def update_screen_view(self, screen_session_id: str, *, fps=None, quality=None) -> dict:
        return self.screen_view_session_service.update_settings(screen_session_id, fps=fps, quality=quality)

    def set_screen_control(self, screen_session_id: str, enabled: bool) -> dict:
        return self.screen_view_session_service.set_control_enabled(screen_session_id, enabled)

    def send_screen_input(self, screen_session_id: str, event: dict) -> dict:
        return self.screen_view_session_service.send_input(screen_session_id, event)

    def close_screen_view(self, screen_session_id: str) -> dict:
        return self.screen_view_session_service.close_session(screen_session_id)

    def poll_screen_view(self, screen_session_id: str, after_seq: int = 0) -> dict:
        return self.screen_view_session_service.get_updates(screen_session_id, after_seq=after_seq)
