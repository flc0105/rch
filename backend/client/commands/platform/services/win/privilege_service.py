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
    @staticmethod
    def _background_launch_arguments():
        """Build an elevated, windowless one-shot bootstrap for a detached Client."""
        import base64
        import os
        import subprocess
        import sys

        from client.watchdog.watchdog_environment import PROCESS_RECOVERY_WATCHDOG_ENV_KEYS
        from client.watchdog.recovery_source import RECOVERY_SOURCE_ENV

        def ps_quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        executable = os.path.realpath(sys.executable)
        argv = list(sys.argv[1:]) if getattr(sys, 'frozen', False) else [
            os.path.realpath(sys.argv[0]), *sys.argv[1:],
        ]
        lines = [
            "$ErrorActionPreference = 'Stop'",
            '$psi = New-Object System.Diagnostics.ProcessStartInfo',
            f'$psi.FileName = {ps_quote(executable)}',
            f'$psi.Arguments = {ps_quote(subprocess.list2cmdline(argv))}',
            f'$psi.WorkingDirectory = {ps_quote(os.getcwd())}',
            '$psi.UseShellExecute = $false',
            '$psi.CreateNoWindow = $true',
            '$psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden',
            "$psi.EnvironmentVariables['RCH_CLIENT_LAUNCH_MODE'] = 'detached'",
            "$psi.EnvironmentVariables['RCH_CLIENT_LAUNCH_SOURCE'] = 'detached_process'",
        ]
        for key in (*PROCESS_RECOVERY_WATCHDOG_ENV_KEYS, RECOVERY_SOURCE_ENV):
            lines.append(f'[void]$psi.EnvironmentVariables.Remove({ps_quote(key)})')
        lines.append('if (-not [System.Diagnostics.Process]::Start($psi)) { exit 1 }')
        encoded = base64.b64encode('\n'.join(lines).encode('utf-16-le')).decode('ascii')
        powershell = os.path.join(
            os.environ.get('SystemRoot', r'C:\Windows'),
            'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe',
        )
        return powershell, f'-NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand {encoded}'

    def spawn_elevated_instance(self, *, bgrun=False):
        """Request UAC elevation; background mode creates a detached windowless Client."""
        import ctypes
        import os
        from client.runtime.client_util import get_exec_and_args

        try:
            if bgrun:
                executable, parameters = self._background_launch_arguments()
            else:
                executable, parameters = get_exec_and_args()
            result = ctypes.windll.shell32.ShellExecuteW(
                None, 'runas', executable, parameters, os.getcwd(), 0 if bgrun else 1,
            )
            if result > 32:
                if bgrun:
                    return 1, 'Elevated background Client launch requested (detached, no console window)'
                return 1, 'Elevated Client launch requested'
            return 0, f'Elevated Client launch failed (ShellExecuteW: {result})'
        except Exception as exc:
            return 0, f'Elevated Client launch failed: {exc}'
