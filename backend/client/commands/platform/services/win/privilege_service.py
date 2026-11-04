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
    def _detached_launch_arguments():
        """Run an elevated PowerShell helper that creates a console-free Client.

        ProcessStartInfo.CreateNoWindow only hides the window; the native
        DETACHED_PROCESS flag is needed to detach the new Client from Console.
        """
        import base64
        import os
        import subprocess

        from client.runtime.client_util import get_executable_argv
        from client.watchdog.watchdog_environment import PROCESS_RECOVERY_WATCHDOG_ENV_KEYS
        from client.watchdog.recovery_source import RECOVERY_SOURCE_ENV

        def ps_quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        launch_argv = get_executable_argv()
        # CreateProcessW requires the executable in the command line too.
        command_line = subprocess.list2cmdline(launch_argv)
        native_source = r"""
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class RchDetachedProcess {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct StartupInfo {
        public int cb; public string reserved; public string desktop;
        public string title; public int x; public int y; public int xSize;
        public int ySize; public int xCountChars; public int yCountChars;
        public int fillAttribute; public int flags; public short showWindow;
        public short reserved2; public IntPtr reserved2Ptr;
        public IntPtr stdInput; public IntPtr stdOutput; public IntPtr stdError;
    }
    [StructLayout(LayoutKind.Sequential)]
    public struct ProcessInfo {
        public IntPtr process; public IntPtr thread;
        public int processId; public int threadId;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, ExactSpelling = true)]
    public static extern bool CreateProcessW(
        string applicationName, StringBuilder commandLine,
        IntPtr processAttributes, IntPtr threadAttributes,
        bool inheritHandles, uint creationFlags, IntPtr environment,
        string currentDirectory, ref StartupInfo startupInfo,
        out ProcessInfo processInfo);
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool CloseHandle(IntPtr handle);
}
"""
        lines = [
            "$ErrorActionPreference = 'Stop'",
            f'Add-Type -TypeDefinition {ps_quote(native_source)}',
        ]
        for key in (*PROCESS_RECOVERY_WATCHDOG_ENV_KEYS, RECOVERY_SOURCE_ENV):
            lines.append(f'Remove-Item -LiteralPath {ps_quote("Env:" + key)} -ErrorAction SilentlyContinue')
        lines.extend([
            '$startup = [RchDetachedProcess+StartupInfo]::new()',
            '$startup.cb = [System.Runtime.InteropServices.Marshal]::SizeOf([RchDetachedProcess+StartupInfo])',
            '$procInfo = [RchDetachedProcess+ProcessInfo]::new()',
            f'$commandLine = [System.Text.StringBuilder]::new({ps_quote(command_line)})',
            # DETACHED_PROCESS (0x8) | CREATE_NEW_PROCESS_GROUP (0x200)
            f'$ok = [RchDetachedProcess]::CreateProcessW({ps_quote(launch_argv[0])}, $commandLine, '
            f'[IntPtr]::Zero, [IntPtr]::Zero, $false, 0x208, [IntPtr]::Zero, '
            f'{ps_quote(os.getcwd())}, [ref]$startup, [ref]$procInfo)',
            'if (-not $ok) { throw ("CreateProcessW failed: " + [Runtime.InteropServices.Marshal]::GetLastWin32Error()) }',
            '[void][RchDetachedProcess]::CloseHandle($procInfo.thread)',
            '[void][RchDetachedProcess]::CloseHandle($procInfo.process)',
        ])
        encoded = base64.b64encode('\n'.join(lines).encode('utf-16-le')).decode('ascii')
        powershell = os.path.join(
            os.environ.get('SystemRoot', r'C:\Windows'),
            'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe',
        )
        return powershell, f'-NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand {encoded}'

    def spawn_elevated_instance(self, *, detached=False):
        """Request UAC elevation; detached mode creates a console-free Client."""
        import ctypes
        import os
        from client.runtime.client_util import get_exec_and_args

        try:
            if detached:
                executable, parameters = self._detached_launch_arguments()
            else:
                executable, parameters = get_exec_and_args()
            result = ctypes.windll.shell32.ShellExecuteW(
                None, 'runas', executable, parameters, os.getcwd(), 0 if detached else 1,
            )
            if result > 32:
                if detached:
                    return 1, 'Elevated detached Client launch requested'
                return 1, 'Elevated Client launch requested'
            return 0, f'Elevated Client launch failed (ShellExecuteW: {result})'
        except Exception as exc:
            return 0, f'Elevated Client launch failed: {exc}'
