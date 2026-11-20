"""Windows UAC launch modes and their isolated Python worker."""

import base64
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
import socket
import struct
import subprocess
import sys

if __package__:
    from client.commands.shell.standalone._elevated_process import ElevationCancelled, run_tracked


# This worker runs under python -I, independently of the Client package.
_PACKET = struct.Struct('!cI')


def _windows_system_directory():
    get_directory = ctypes.WinDLL('kernel32', use_last_error=True).GetSystemDirectoryW
    get_directory.argtypes = (wintypes.LPWSTR, wintypes.UINT)
    get_directory.restype = wintypes.UINT
    path = ctypes.create_unicode_buffer(32768)
    if not 0 < get_directory(path, len(path)) < len(path):
        raise ctypes.WinError(ctypes.get_last_error())
    return path.value


def run_windows_helper(payload):
    """Run one authorized Windows command in this auxiliary process."""

    def send(kind, data):
        channel.sendall(_PACKET.pack(kind, len(data)) + data)

    def stop_shell(child):
        try:
            subprocess.run(
                [os.path.join(system_directory, 'taskkill.exe'), '/pid', str(child.pid), '/t', '/f'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        if child.poll() is None:
            child.kill()
        child.wait()

    request = json.loads(base64.b64decode(payload))
    with socket.create_connection(('127.0.0.1', request['port']), timeout=5) as channel:
        send(b'T', request['token'].encode('ascii'))
        with channel.makefile('rb') as incoming:
            if incoming.read(len(request['ack'])) != request['ack'].encode('ascii'):
                return 1

        child = None
        try:
            if request['mode'] == 'detached':
                if os.path.splitext(request['command'][0])[1].lower() in ('.bat', '.cmd'):
                    raise OSError('Use --shell to run a Windows batch file')
                child = subprocess.Popen(
                    request['command'], cwd=request['cwd'], env=os.environ.copy(),
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                )
                send(b'P', str(child.pid).encode('ascii'))
            else:
                import msvcrt
                import select

                system_directory = _windows_system_directory()
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                executable = os.path.join(system_directory, 'cmd.exe')
                # /s removes one pair of outer quotes, preserving the user's shell text.
                command_line = subprocess.list2cmdline([executable]) + ' /d /s /c "' + request['command'] + '"'
                peek = kernel.PeekNamedPipe
                peek.argtypes = (wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                 wintypes.LPDWORD, wintypes.LPDWORD, wintypes.LPDWORD)
                peek.restype = wintypes.BOOL
                child = subprocess.Popen(
                    command_line, executable=executable, cwd=request['cwd'],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                with child.stdout:
                    pipe = msvcrt.get_osfhandle(child.stdout.fileno())
                    available = wintypes.DWORD()
                    while True:
                        if select.select([channel], [], [], 0)[0] and not channel.recv(1):
                            break
                        return_code = child.poll()
                        if peek(pipe, None, 0, None, ctypes.byref(available), None):
                            if available.value:
                                send(b'O', os.read(child.stdout.fileno(), min(8192, available.value)))
                                continue
                        elif ctypes.get_last_error() not in (109, 232):  # closed pipe
                            raise ctypes.WinError(ctypes.get_last_error())
                        if return_code is not None:
                            send(b'X', str(return_code).encode('ascii'))
                            break
                        select.select([channel], [], [], 0.05)
        except OSError as error:
            send(b'E', str(error).encode('utf-8'))
        finally:
            if child is not None and request['mode'] == 'shell' and child.poll() is None:
                stop_shell(child)
    return 0


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND),
        ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
        ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
        ('lpIDList', wintypes.LPVOID), ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
        ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE),
    ]


@contextmanager
def _windows_launch(executable, arguments, cwd, *, show):
    shell32 = ctypes.WinDLL('shell32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    execute = shell32.ShellExecuteExW
    execute.argtypes = (ctypes.POINTER(_ShellExecuteInfo),)
    execute.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    info = _ShellExecuteInfo(
        cbSize=ctypes.sizeof(_ShellExecuteInfo),
        fMask=0x00000040 | 0x00000100 | 0x00000400,  # NOCLOSEPROCESS, NOASYNC, FLAG_NO_UI
        lpVerb='runas', lpFile=executable, lpParameters=arguments, lpDirectory=cwd, nShow=show,
    )
    if not execute(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == 1223:
            raise ElevationCancelled('Windows UAC authorization cancelled')
        raise ctypes.WinError(error)
    try:
        yield kernel32, info.hProcess
    finally:
        if info.hProcess:
            close_handle(info.hProcess)


@contextmanager
def _launch_helper(payload, cwd):
    arguments = subprocess.list2cmdline(['-I', os.path.abspath(__file__), payload])
    with _windows_launch(sys.executable, arguments, cwd, show=0) as (kernel, process):
        if not process:
            raise OSError('Windows did not return the elevated helper process')
        wait = kernel.WaitForSingleObject
        wait.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        wait.restype = wintypes.DWORD

        def error_if_exited():
            if wait(process, 0) == 0:
                raise OSError('Elevated helper exited before it could start the command')

        yield error_if_exited


class WindowsElevation:
    def __init__(self, owner):
        self.owner = owner

    def shell(self, command):
        return self._run_shell(command, collect=False)

    def collect(self, command):
        return self._run_shell(command, collect=True)

    def _run_shell(self, command, *, collect):
        encoding = f'cp{ctypes.windll.kernel32.GetOEMCP()}' if os.name == 'nt' else 'utf-8'
        return run_tracked(self.owner, _launch_helper, 'shell', command, encoding=encoding, collect=collect)

    def detached(self, argv):
        return run_tracked(self.owner, _launch_helper, 'detached', argv)

    def open(self, argv):
        executable, *args = argv
        arguments = subprocess.list2cmdline(args) or None
        with _windows_launch(executable, arguments, os.getcwd(), show=1) as (kernel, process):
            if process:
                get_pid = kernel.GetProcessId
                get_pid.argtypes = (wintypes.HANDLE,)
                get_pid.restype = wintypes.DWORD
                pid = get_pid(process)
                if pid:
                    return 1, f'Opened elevated program (PID: {pid})'
            return 1, 'Elevated program open requested'

    def show_console(self, command):
        execute = ctypes.WinDLL('shell32', use_last_error=True).ShellExecuteW
        execute.argtypes = (
            wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
            wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int,
        )
        execute.restype = ctypes.c_ssize_t
        result = execute(None, 'runas', 'cmd.exe', f'/c {command}', None, 1)
        if result > 32:
            return 1, f'Executed: {command}'
        if ctypes.get_last_error() == 1223:
            raise ElevationCancelled('Windows UAC authorization cancelled')
        return 0, f'Failed to open elevated console (Windows Shell error {result})'


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Expected one elevation request')
    sys.exit(run_windows_helper(sys.argv[1]))
