class WinPrivilegeService:
    """
    Windows 提权/管理员执行能力。
    """

    def __init__(self, owner):
        self.owner = owner

    def run_as_admin(self, command):
        import ctypes
        try:
            result = ctypes.windll.shell32.ShellExecuteW(
                None,
                'runas',
                'cmd.exe',
                f'/c {command}',
                None,
                1,
            )
            if result > 32:
                return 1, f'Executed: {command}'
            return 0, f'Failed with code: {result}'
        except Exception as e:
            return 0, f'Failed: {e}'
    def spawn_elevated_instance(self):
        """Request UAC elevation for this Client, preserving its launch arguments."""
        import ctypes
        import os
        from client.runtime.client_util import get_exec_and_args

        executable, parameters = get_exec_and_args()
        try:
            result = ctypes.windll.shell32.ShellExecuteW(
                None, 'runas', executable, parameters, os.getcwd(), 1,
            )
            if result > 32:
                return 1, 'Elevated Client launch requested'
            return 0, f'Elevated Client launch failed (ShellExecuteW: {result})'
        except Exception as exc:
            return 0, f'Elevated Client launch failed: {exc}'
