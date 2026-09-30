import os
import sys
import subprocess

import win32api
import win32con
import win32process
import win32profile
import win32security
import win32ts


def enable_privilege(privilege_name):
    """
    SYSTEM 通常拥有这些权限，但可能处于 disabled 状态。
    CreateProcessAsUser 常用：
      - SeAssignPrimaryTokenPrivilege
      - SeIncreaseQuotaPrivilege
    """
    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(),
        win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY,
    )

    luid = win32security.LookupPrivilegeValue(None, privilege_name)

    win32security.AdjustTokenPrivileges(
        token,
        False,
        [(luid, win32con.SE_PRIVILEGE_ENABLED)],
    )


def find_active_session():
    """
    找一个当前处于 WTSActive 状态的交互式用户会话。
    对 RDP 也比单纯 WTSGetActiveConsoleSessionId 更合适。
    """
    sessions = win32ts.WTSEnumerateSessions(
        win32ts.WTS_CURRENT_SERVER_HANDLE,
        1,
        0,
    )

    candidates = []

    for session in sessions:
        if session["State"] != win32ts.WTSActive:
            continue

        session_id = session["SessionId"]

        try:
            username = win32ts.WTSQuerySessionInformation(
                win32ts.WTS_CURRENT_SERVER_HANDLE,
                session_id,
                win32ts.WTSUserName,
            )

            domain = win32ts.WTSQuerySessionInformation(
                win32ts.WTS_CURRENT_SERVER_HANDLE,
                session_id,
                win32ts.WTSDomainName,
            )
        except Exception:
            continue

        if not username:
            continue

        candidates.append((session_id, domain, username))

    if not candidates:
        raise RuntimeError("没有找到处于 Active 状态的交互式登录用户")

    # 如果只有一个活跃用户，直接用它。
    # 多用户/RDS 环境建议改成显式指定 session id。
    return candidates[0]


def launch_as_logged_on_user(exe, args=None, cwd=None):
    args = args or []

    exe = os.path.abspath(exe)

    if not os.path.exists(exe):
        raise FileNotFoundError(exe)

    if cwd is None:
        cwd = os.path.dirname(exe)

    enable_privilege("SeAssignPrimaryTokenPrivilege")
    enable_privilege("SeIncreaseQuotaPrivilege")

    session_id, domain, username = find_active_session()

    print(
        f"[+] active session: {session_id} "
        f"user={domain}\\{username}"
    )

    # SYSTEM 调用时可以获取该登录会话的用户 token
    user_token = win32ts.WTSQueryUserToken(session_id)

    # 复制成 Primary Token，供 CreateProcessAsUser 使用
    primary_token = win32security.DuplicateTokenEx(
        user_token,
        win32security.SecurityImpersonation,
        win32con.MAXIMUM_ALLOWED,
        win32security.TokenPrimary,
        None,
    )

    # 构建目标用户自己的环境变量，例如 USERPROFILE、TEMP、APPDATA 等
    environment = win32profile.CreateEnvironmentBlock(
        primary_token,
        False,
    )

    startup = win32process.STARTUPINFO()

    # 很关键：
    # 否则从 service / SYSTEM Session 0 启动时可能无法出现在用户桌面
    startup.lpDesktop = r"winsta0\default"

    command_line = subprocess.list2cmdline(
        [exe] + list(args)
    )

    flags = (
        win32con.CREATE_UNICODE_ENVIRONMENT
        | win32con.CREATE_NEW_CONSOLE
    )

    print(f"[+] launching: {command_line}")
    print(f"[+] cwd: {cwd}")

    process_handle, thread_handle, pid, tid = (
        win32process.CreateProcessAsUser(
            primary_token,
            exe,
            command_line,
            None,
            None,
            False,
            flags,
            environment,
            cwd,
            startup,
        )
    )

    print(f"[+] started PID={pid}")

    thread_handle.Close()
    process_handle.Close()
    primary_token.Close()
    user_token.Close()

    return pid


if __name__ == "__main__":
    # 修改成你实际要启动的程序
    target_exe = r"C:\\windows\\system32\\cmd.exe"

    pid = launch_as_logged_on_user(
        target_exe,
        args=[
            # "--foo",
            # "bar",
        ],
    )

    print(f"PID: {pid}")