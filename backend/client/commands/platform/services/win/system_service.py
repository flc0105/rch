

class WinSystemService:
    """
    Windows 系统信息与用户状态能力。
    """

    def __init__(self, owner):
        self.owner = owner

    def get_user_idletime(self):
        try:
            import win32api

            idle_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
            idle_seconds = idle_ms / 1000.0

            return 1, f'User idle time: {idle_seconds:.2f} seconds'

        except Exception as e:
            return 0, f'Failed to get idle time: {e}'