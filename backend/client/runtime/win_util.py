import ctypes
from ctypes.wintypes import DWORD, HANDLE, LPBYTE, LPWSTR, WORD

import ntsecuritycon
import psutil
import win32api
import win32con
import win32process
import win32security
import win32service
import winerror

kernel32 = ctypes.windll.kernel32
advapi32 = ctypes.windll.advapi32


def get_integrity_level() -> str:
    """
    获取当前进程的完整性级别
    """
    mapping = {
        0x0000: 'Untrusted',
        0x1000: 'Low',
        0x2000: 'Medium',
        0x2100: 'Medium High',
        0x3000: 'High',
        0x4000: 'System',
        0x5000: 'Protected',
    }

    try:
        h_token = win32security.OpenProcessToken(
            win32process.GetCurrentProcess(),
            win32security.TOKEN_READ
        )
        sid = win32security.GetTokenInformation(h_token, ntsecuritycon.TokenIntegrityLevel)[0]
        return mapping.get(sid.GetSubAuthority(sid.GetSubAuthorityCount() - 1), 'Unknown')
    except Exception:
        return 'Unknown'


def logon_user(username, password):
    """验证用户凭证"""
    try:
        token = win32security.LogonUser(username, None, password, win32security.LOGON32_LOGON_INTERACTIVE,
                                        win32security.LOGON32_PROVIDER_DEFAULT)
        token.Close()
        return True
    except win32security.error as e:
        if e.winerror == winerror.ERROR_ACCOUNT_RESTRICTION:
            return True
        if e.winerror == winerror.ERROR_LOGON_FAILURE:
            return False
        return False


def enable_privilege(privilege_name):
    """启用指定权限"""
    h_token = win32security.OpenProcessToken(win32process.GetCurrentProcess(),
                                             win32security.TOKEN_ADJUST_PRIVILEGES | win32security.TOKEN_QUERY)
    privilege_id = win32security.LookupPrivilegeValue(None, privilege_name)
    new_privilege = [(privilege_id, win32con.SE_PRIVILEGE_ENABLED)]
    win32security.AdjustTokenPrivileges(h_token, 0, new_privilege)
    win32api.CloseHandle(h_token)


def get_pid(process_name):
    """根据进程名获取 PID"""
    for proc in psutil.process_iter(['name']):
        if process_name.lower() in proc.info['name'].lower():
            return proc.pid
    return None


def get_process_token(pid):
    """获取进程 Token"""
    h_process = kernel32.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, pid)
    return win32security.OpenProcessToken(h_process, win32con.TOKEN_DUPLICATE | win32con.TOKEN_QUERY)


def duplicate_token(h_token):
    """复制 Token"""
    return win32security.DuplicateTokenEx(h_token, win32security.SecurityImpersonation, win32con.MAXIMUM_ALLOWED,
                                          win32security.TokenPrimary, win32security.SECURITY_ATTRIBUTES())


def start_service(service_name):
    """启动服务"""
    h_scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
    h_service = win32service.OpenService(h_scm, service_name,
                                         win32service.SERVICE_START | win32service.SERVICE_QUERY_STATUS)
    status = win32service.QueryServiceStatus(h_service)[1]
    if status == win32service.SERVICE_STOPPED:
        win32service.StartService(h_service, None)
    win32service.CloseServiceHandle(h_service)


def create_process_with_token(h_token, lp_application_name, lp_command_line):
    """使用 Token 创建进程"""

    class STARTUPINFO(ctypes.Structure):
        _fields_ = (('cb', DWORD),
                    ('lpReserved', LPWSTR),
                    ('lpDesktop', LPWSTR),
                    ('lpTitle', LPWSTR),
                    ('dwX', DWORD),
                    ('dwY', DWORD),
                    ('dwXSize', DWORD),
                    ('dwYSize', DWORD),
                    ('dwXCountChars', DWORD),
                    ('dwYCountChars', DWORD),
                    ('dwFillAttribute', DWORD),
                    ('dwFlags', DWORD),
                    ('wShowWindow', WORD),
                    ('cbReserved2', WORD),
                    ('lpReserved2', LPBYTE),
                    ('hStdInput', HANDLE),
                    ('hStdOutput', HANDLE),
                    ('hStdError', HANDLE))

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = (('hProcess', HANDLE),
                    ('hThread', HANDLE),
                    ('dwProcessId', DWORD),
                    ('dwThreadId', DWORD))

    si = STARTUPINFO()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = 'winsta0\\default'
    pi = PROCESS_INFORMATION()
    creation_flags = win32con.CREATE_NEW_CONSOLE | win32con.NORMAL_PRIORITY_CLASS | win32con.CREATE_UNICODE_ENVIRONMENT
    advapi32.CreateProcessWithTokenW(int(h_token), 1, lp_application_name, lp_command_line, creation_flags, None, None,
                                     ctypes.byref(si), ctypes.byref(pi))
    return pi.dwProcessId


def get_windows_uid_gid_sid():
    from ctypes import wintypes
    import os
    if os.name != "nt":
        raise OSError("Windows only")

    TOKEN_QUERY = 0x0008
    TokenUser = 1
    TokenPrimaryGroup = 5

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("Sid", wintypes.LPVOID),
            ("Attributes", wintypes.DWORD),
        ]

    class TOKEN_USER(ctypes.Structure):
        _fields_ = [
            ("User", SID_AND_ATTRIBUTES),
        ]

    class TOKEN_PRIMARY_GROUP(ctypes.Structure):
        _fields_ = [
            ("PrimaryGroup", wintypes.LPVOID),
        ]

    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL

    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL

    advapi32.ConvertSidToStringSidW.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL

    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.LocalFree.argtypes = [wintypes.LPVOID]

    def raise_last_error():
        raise ctypes.WinError(ctypes.get_last_error())

    def get_token_information(token, info_class):
        needed = wintypes.DWORD(0)

        advapi32.GetTokenInformation(
            token,
            info_class,
            None,
            0,
            ctypes.byref(needed),
        )

        if needed.value == 0:
            raise_last_error()

        buf = ctypes.create_string_buffer(needed.value)

        ok = advapi32.GetTokenInformation(
            token,
            info_class,
            buf,
            needed.value,
            ctypes.byref(needed),
        )

        if not ok:
            raise_last_error()

        return buf

    def sid_to_string(psid):
        sid_string = wintypes.LPWSTR()

        ok = advapi32.ConvertSidToStringSidW(
            psid,
            ctypes.byref(sid_string),
        )

        if not ok:
            raise_last_error()

        try:
            return sid_string.value
        finally:
            kernel32.LocalFree(sid_string)

    token = wintypes.HANDLE()

    ok = advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        TOKEN_QUERY,
        ctypes.byref(token),
    )

    if not ok:
        raise_last_error()

    try:
        user_buf = get_token_information(token, TokenUser)
        user = ctypes.cast(user_buf, ctypes.POINTER(TOKEN_USER)).contents
        uid = sid_to_string(user.User.Sid)

        group_buf = get_token_information(token, TokenPrimaryGroup)
        group = ctypes.cast(
            group_buf,
            ctypes.POINTER(TOKEN_PRIMARY_GROUP),
        ).contents
        gid = sid_to_string(group.PrimaryGroup)

        return {
            "uid": uid,
            "gid": gid,
        }

    finally:
        kernel32.CloseHandle(token)


def get_locale_tag(default=""):
    import os,re
    def normalize(value):
        if not value:
            return None

        value = value.strip()

        if not value:
            return None

        # 处理 zh_CN.UTF-8、zh_CN:en_US、zh_CN@variant
        value = value.split(":", 1)[0]
        value = value.split(".", 1)[0]
        value = value.split("@", 1)[0]

        if value.upper() in {"C", "POSIX"}:
            return None

        parts = [p for p in re.split(r"[-_]", value) if p]

        if not parts:
            return None

        result = [parts[0].lower()]

        for part in parts[1:]:
            if len(part) == 4 and part.isalpha():
                # Hans / Hant
                result.append(part.title())
            elif len(part) == 2 and part.isalpha():
                # CN / US
                result.append(part.upper())
            elif len(part) == 3 and part.isdigit():
                # 419
                result.append(part)
            else:
                result.append(part)

        return "-".join(result)

    # Windows 优先用系统 API
    if os.name == "nt":
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetUserDefaultLocaleName.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_int,
            ]
            kernel32.GetUserDefaultLocaleName.restype = ctypes.c_int

            buf = ctypes.create_unicode_buffer(85)
            n = kernel32.GetUserDefaultLocaleName(buf, len(buf))

            if n:
                tag = normalize(buf.value)
                if tag:
                    return tag
        except Exception:
            pass

