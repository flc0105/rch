import os
import subprocess

import win32api
import win32con
import win32process
import win32profile
import win32security
import win32ts


def enable_privilege(privilege_name):
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
    token.Close()


def find_active_session():
    """
    pywin32 的 WTSEnumerateSessions 只接受 (hServer, Version) 两个参数。
    Version 必须为 1。
    """
    sessions = win32ts.WTSEnumerateSessions(
        win32ts.WTS_CURRENT_SERVER_HANDLE,
        1,
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

    return candidates[0]


def dup_primary_token(token):
    """
    按 pywin32 的正确参数顺序复制为主令牌：
        DuplicateTokenEx(ExistingToken,
                         ImpersonationLevel,
                         DesiredAccess,
                         TokenType,
                         TokenAttributes)
    TokenAttributes 传 None 表示 NULL。
    """
    return win32security.DuplicateTokenEx(
        token,
        win32security.SecurityImpersonation,
        win32con.MAXIMUM_ALLOWED,
        win32security.TokenPrimary,
        None,
    )


def get_elevated_token(filtered_token):
    """
    从过滤令牌获取链接的提升令牌。
    """
    has_restrictions = win32security.GetTokenInformation(
        filtered_token, win32security.TokenHasRestrictions
    )

    if not has_restrictions:
        # 已是完整令牌
        return dup_primary_token(filtered_token)

    try:
        linked_token = win32security.GetTokenInformation(
            filtered_token, win32security.TokenLinkedToken
        )
    except Exception as e:
        raise RuntimeError(
            "无法获取链接令牌（用户可能不是管理员，"
            "或 UAC 拆分令牌不可用）"
        ) from e

    is_elevated = win32security.GetTokenInformation(
        linked_token, win32security.TokenElevation
    )
    if not is_elevated:
        linked_token.Close()
        raise RuntimeError("链接令牌不是提升令牌")

    primary_token = dup_primary_token(linked_token)
    linked_token.Close()
    return primary_token


def launch_as_logged_on_user(exe, args=None, cwd=None, require_elevation=True):
    args = args or []
    exe = os.path.abspath(exe)
    if not os.path.exists(exe):
        raise FileNotFoundError(exe)

    if cwd is None:
        cwd = os.path.dirname(exe)

    enable_privilege("SeAssignPrimaryTokenPrivilege")
    enable_privilege("SeIncreaseQuotaPrivilege")

    session_id, domain, username = find_active_session()
    print(f"[+] active session: {session_id} user={domain}\\{username}")

    user_token = win32ts.WTSQueryUserToken(session_id)

    try:
        primary_token = get_elevated_token(user_token)
        print("[+] 已获取提升的管理员令牌")
    except RuntimeError as e:
        if require_elevation:
            user_token.Close()
            raise RuntimeError(f"无法获取提升令牌: {e}") from e
        print(f"[!] 无法获取提升令牌: {e}")
        print("[!] 回退到普通用户令牌启动")
        primary_token = dup_primary_token(user_token)

    environment = win32profile.CreateEnvironmentBlock(primary_token, False)

    startup = win32process.STARTUPINFO()
    startup.lpDesktop = r"winsta0\default"

    command_line = subprocess.list2cmdline([exe] + list(args))

    flags = (
        win32con.CREATE_UNICODE_ENVIRONMENT
        | win32con.CREATE_NEW_CONSOLE
    )

    print(f"[+] launching: {command_line}")
    print(f"[+] cwd: {cwd}")

    process_handle, thread_handle, pid, tid = win32process.CreateProcessAsUser(
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

    print(f"[+] started PID={pid}")

    thread_handle.Close()
    process_handle.Close()
    primary_token.Close()
    user_token.Close()

    return pid


if __name__ == "__main__":
    target_exe = r"C:\windows\system32\cmd.exe"

    pid = launch_as_logged_on_user(
        target_exe,
        args=[],
        require_elevation=True,
    )
    print(f"PID: {pid}")