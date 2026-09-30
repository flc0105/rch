import os
import subprocess
import sys

import win32api
import win32con
import win32process
import win32profile
import win32security
import win32ts

from client.runtime.client_util import get_exec_and_args



TokenElevationTypeDefault = 1
TokenElevationTypeFull = 2
TokenElevationTypeLimited = 3

_ETYPE_MAP = {
    TokenElevationTypeDefault: "Default (无 linked token)",
    TokenElevationTypeFull:    "Full (elevated)",
    TokenElevationTypeLimited: "Limited (UAC filtered)",
}

SYSTEM_PROFILE = os.path.normpath(
    r"C:\Windows\System32\config\systemprofile"
)


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


def dump_token_info(token, label=""):
    elevation = win32security.GetTokenInformation(
        token, win32security.TokenElevation
    )
    elevation_type = win32security.GetTokenInformation(
        token, win32security.TokenElevationType
    )
    restricted = win32security.GetTokenInformation(
        token, win32security.TokenHasRestrictions
    )

    print(f"--- token info [{label}] ---")
    print(f"  TokenElevation       = {elevation}")
    print(f"  TokenElevationType   = {elevation_type} "
          f"({_ETYPE_MAP.get(elevation_type, 'Unknown')})")
    print(f"  TokenHasRestrictions = {restricted}")

    return {
        "elevation": elevation,
        "elevation_type": elevation_type,
        "restricted": restricted,
    }


def inspect_linked_token(user_token):
    etype = win32security.GetTokenInformation(
        user_token, win32security.TokenElevationType
    )
    if etype != TokenElevationTypeLimited:
        print(f"[!] 当前 token 不是 Limited，ElevationType = {etype}")
        return

    linked = win32security.GetTokenInformation(
        user_token, win32security.TokenLinkedToken
    )
    try:
        print("\n=== filtered token ===")
        dump_token_info(user_token, "filtered")

        print("\n=== linked token ===")
        dump_token_info(linked, "linked")

        filtered_sid = win32security.GetTokenInformation(
            user_token, win32security.TokenUser
        )[0]
        linked_sid = win32security.GetTokenInformation(
            linked, win32security.TokenUser
        )[0]
        print("filtered SID =",
              win32security.ConvertSidToStringSid(filtered_sid))
        print("linked SID   =",
              win32security.ConvertSidToStringSid(linked_sid))

        filtered_session = win32security.GetTokenInformation(
            user_token, win32security.TokenSessionId
        )
        linked_session = win32security.GetTokenInformation(
            linked, win32security.TokenSessionId
        )
        print(f"filtered session = {filtered_session}")
        print(f"linked session   = {linked_session}")
    finally:
        linked.Close()


def dup_primary_token(token):
    """
    pywin32 DuplicateTokenEx 正确参数顺序：
        (ExistingToken, ImpersonationLevel, DesiredAccess, TokenType, TokenAttributes)
    """
    return win32security.DuplicateTokenEx(
        token,
        win32security.SecurityImpersonation,
        win32con.MAXIMUM_ALLOWED,
        win32security.TokenPrimary,
        None,
    )


def get_elevated_token(user_token):
    info = dump_token_info(user_token, "WTSQueryUserToken")
    etype = info["elevation_type"]

    if etype == TokenElevationTypeFull:
        return dup_primary_token(user_token)

    if etype == TokenElevationTypeLimited:
        linked_token = win32security.GetTokenInformation(
            user_token, win32security.TokenLinkedToken
        )
        try:
            linked_info = dump_token_info(linked_token, "linked")
            if linked_info["elevation_type"] != TokenElevationTypeFull:
                raise RuntimeError(
                    "linked token 的 ElevationType 不是 Full"
                )
            return dup_primary_token(linked_token)
        finally:
            linked_token.Close()

    if etype == TokenElevationTypeDefault:
        raise RuntimeError(
            "TokenElevationTypeDefault：当前 token 无 linked token"
        )

    raise RuntimeError(f"未知 TokenElevationType = {etype}")


def normalize_args(args):
    """
    把 args 归一化成 list[str]。
    - None            -> []
    - str             -> [str]
    - list/tuple      -> list(args)
    - 其他 iterable   -> list(args)
    """
    if args is None:
        return []
    if isinstance(args, (str, bytes, os.PathLike)):
        return [os.fspath(args)]
    return [os.fspath(a) if isinstance(a, os.PathLike) else str(a)
            for a in args]


def rebase_systemprofile_path(path, user_profile):
    """
    如果 path 位于 systemprofile 下，则替换成 user_profile 下对应的路径。
    不属于 systemprofile 时原样返回。
    """
    if not user_profile:
        return path

    path = os.path.normpath(path)
    try:
        relative = os.path.relpath(path, SYSTEM_PROFILE)
    except ValueError:
        return path

    if relative == ".." or relative.startswith(".." + os.sep):
        return path

    return os.path.normpath(os.path.join(user_profile, relative))


def rebase_if_exists(path, user_profile):
    """
    只有转换后路径真实存在才采用；否则原样返回并告警。
    """
    new_path = rebase_systemprofile_path(path, user_profile)
    if new_path == path:
        return path

    if os.path.exists(new_path):
        print(f"[+] rebase: {path}\n           -> {new_path}")
        return new_path

    print(f"[!] rebase 目标不存在，保持原路径: {path}")
    return path


def launch_as_logged_on_user(exe, args=None, cwd=None):
    args = normalize_args(args)

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
        print("[+] 已获取 elevated primary token")
    except RuntimeError:
        user_token.Close()
        raise

    # 用 primary_token 构建环境块，拿到 USERPROFILE
    environment = win32profile.CreateEnvironmentBlock(primary_token, False)
    user_profile = environment.get("USERPROFILE")
    print(f"[+] target USERPROFILE: {user_profile}")

    # 如果 exe 或某个参数落在 systemprofile 下，尝试重定位到用户目录
    exe = rebase_if_exists(exe, user_profile)
    args = [rebase_if_exists(a, user_profile) for a in args]

    startup = win32process.STARTUPINFO()
    startup.lpDesktop = r"winsta0\default"

    command_line = subprocess.list2cmdline([exe] + args)
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
    enable_privilege("SeAssignPrimaryTokenPrivilege")
    enable_privilege("SeIncreaseQuotaPrivilege")

    session_id, domain, username = find_active_session()
    print(f"[+] active session: {session_id} user={domain}\\{username}")

    # 诊断（只读）
    user_token = win32ts.WTSQueryUserToken(session_id)
    try:
        inspect_linked_token(user_token)
    finally:
        user_token.Close()

    # 取目标程序/参数
    exe_path, argv = get_exec_and_args()
    print(f"[+] exec = {exe_path}")
    print(f"[+] argv = {argv!r}")   # 注意用 !r，确认是 list 还是 str

    pid = launch_as_logged_on_user(
        exe_path,
        args=argv,
        # cwd 不传，默认取 exe 所在目录；也可显式指定用户目录下的位置
    )
    print(f"PID: {pid}")
    
    
    # import os
# import subprocess

# import win32api
# import win32con
# import win32process
# import win32profile
# import win32security
# import win32ts

# from client.runtime.client_util import get_exec_and_args


# TokenElevationTypeDefault = 1
# TokenElevationTypeFull = 2
# TokenElevationTypeLimited = 3

# _ETYPE_MAP = {
#     TokenElevationTypeDefault: "Default (无 linked token)",
#     TokenElevationTypeFull:    "Full (elevated)",
#     TokenElevationTypeLimited: "Limited (UAC filtered)",
# }


# def enable_privilege(privilege_name):
#     token = win32security.OpenProcessToken(
#         win32api.GetCurrentProcess(),
#         win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY,
#     )
#     luid = win32security.LookupPrivilegeValue(None, privilege_name)
#     win32security.AdjustTokenPrivileges(
#         token,
#         False,
#         [(luid, win32con.SE_PRIVILEGE_ENABLED)],
#     )
#     token.Close()


# def find_active_session():
#     sessions = win32ts.WTSEnumerateSessions(
#         win32ts.WTS_CURRENT_SERVER_HANDLE,
#         1,
#     )

#     candidates = []
#     for session in sessions:
#         if session["State"] != win32ts.WTSActive:
#             continue

#         session_id = session["SessionId"]
#         try:
#             username = win32ts.WTSQuerySessionInformation(
#                 win32ts.WTS_CURRENT_SERVER_HANDLE,
#                 session_id,
#                 win32ts.WTSUserName,
#             )
#             domain = win32ts.WTSQuerySessionInformation(
#                 win32ts.WTS_CURRENT_SERVER_HANDLE,
#                 session_id,
#                 win32ts.WTSDomainName,
#             )
#         except Exception:
#             continue

#         if not username:
#             continue

#         candidates.append((session_id, domain, username))

#     if not candidates:
#         raise RuntimeError("没有找到处于 Active 状态的交互式登录用户")

#     return candidates[0]


# def dump_token_info(token, label=""):
#     elevation = win32security.GetTokenInformation(
#         token, win32security.TokenElevation
#     )
#     elevation_type = win32security.GetTokenInformation(
#         token, win32security.TokenElevationType
#     )
#     restricted = win32security.GetTokenInformation(
#         token, win32security.TokenHasRestrictions
#     )

#     print(f"--- token info [{label}] ---")
#     print(f"  TokenElevation       = {elevation}")
#     print(f"  TokenElevationType   = {elevation_type} "
#           f"({_ETYPE_MAP.get(elevation_type, 'Unknown')})")
#     print(f"  TokenHasRestrictions = {restricted}")

#     return {
#         "elevation": elevation,
#         "elevation_type": elevation_type,
#         "restricted": restricted,
#     }


# def inspect_linked_token(user_token):
#     """
#     只读诊断：确认 linked token 是否与 filtered token 同 SID、同 Session，
#     且 ElevationType 为 Full。
#     """
#     etype = win32security.GetTokenInformation(
#         user_token, win32security.TokenElevationType
#     )
#     if etype != TokenElevationTypeLimited:
#         print(f"[!] 当前 token 不是 Limited，ElevationType = {etype}")
#         return

#     linked = win32security.GetTokenInformation(
#         user_token, win32security.TokenLinkedToken
#     )
#     try:
#         print("\n=== filtered token ===")
#         dump_token_info(user_token, "filtered")

#         print("\n=== linked token ===")
#         dump_token_info(linked, "linked")

#         filtered_sid = win32security.GetTokenInformation(
#             user_token, win32security.TokenUser
#         )[0]
#         linked_sid = win32security.GetTokenInformation(
#             linked, win32security.TokenUser
#         )[0]

#         print("filtered SID =",
#               win32security.ConvertSidToStringSid(filtered_sid))
#         print("linked SID   =",
#               win32security.ConvertSidToStringSid(linked_sid))

#         filtered_session = win32security.GetTokenInformation(
#             user_token, win32security.TokenSessionId
#         )
#         linked_session = win32security.GetTokenInformation(
#             linked, win32security.TokenSessionId
#         )
#         print(f"filtered session = {filtered_session}")
#         print(f"linked session   = {linked_session}")
#     finally:
#         linked.Close()


# def dup_primary_token(token):
#     """
#     pywin32 DuplicateTokenEx 正确参数顺序：
#         (ExistingToken, ImpersonationLevel, DesiredAccess, TokenType, TokenAttributes)
#     """
#     return win32security.DuplicateTokenEx(
#         token,
#         win32security.SecurityImpersonation,
#         win32con.MAXIMUM_ALLOWED,
#         win32security.TokenPrimary,
#         None,
#     )


# def get_elevated_token(user_token, require_elevation=True):
#     """
#     按 TokenElevationType 分类处理：
#       Full    -> 已经是提升 token，直接复制
#       Limited -> 取 TokenLinkedToken，校验 Full 后复制
#       Default -> 无 linked token，按 require_elevation 决定是否抛错
#     """
#     info = dump_token_info(user_token, "WTSQueryUserToken")
#     etype = info["elevation_type"]

#     if etype == TokenElevationTypeFull:
#         return dup_primary_token(user_token)

#     if etype == TokenElevationTypeLimited:
#         linked_token = win32security.GetTokenInformation(
#             user_token, win32security.TokenLinkedToken
#         )
#         try:
#             linked_info = dump_token_info(linked_token, "linked")
#             if linked_info["elevation_type"] != TokenElevationTypeFull:
#                 raise RuntimeError(
#                     "linked token 的 ElevationType 不是 Full，"
#                     "不能作为 elevated primary token"
#                 )
#             return dup_primary_token(linked_token)
#         finally:
#             linked_token.Close()

#     if etype == TokenElevationTypeDefault:
#         raise RuntimeError(
#             "TokenElevationTypeDefault：当前 token 无 linked token"
#             "（标准用户 / SYSTEM / UAC 关闭）"
#         )

#     raise RuntimeError(f"未知 TokenElevationType = {etype}")


# def launch_as_logged_on_user(exe, args=None, cwd=None, require_elevation=True):
#     args = args or []
#     exe = os.path.abspath(exe)
#     if not os.path.exists(exe):
#         raise FileNotFoundError(exe)

#     if cwd is None:
#         cwd = os.path.dirname(exe)

#     enable_privilege("SeAssignPrimaryTokenPrivilege")
#     enable_privilege("SeIncreaseQuotaPrivilege")

#     session_id, domain, username = find_active_session()
#     print(f"[+] active session: {session_id} user={domain}\\{username}")

#     user_token = win32ts.WTSQueryUserToken(session_id)

#     try:
#         primary_token = get_elevated_token(user_token)
#         print("[+] 已获取 elevated primary token")
#     except RuntimeError:
#         if require_elevation:
#             user_token.Close()
#             raise
#         print("[!] 回退到普通用户令牌启动")
#         primary_token = dup_primary_token(user_token)

#     environment = win32profile.CreateEnvironmentBlock(primary_token, False)

#     startup = win32process.STARTUPINFO()
#     startup.lpDesktop = r"winsta0\default"

#     command_line = subprocess.list2cmdline([exe] + list(args))
#     flags = (
#         win32con.CREATE_UNICODE_ENVIRONMENT
#         | win32con.CREATE_NEW_CONSOLE
#     )

#     print(f"[+] launching: {command_line}")
#     print(f"[+] cwd: {cwd}")

#     process_handle, thread_handle, pid, tid = win32process.CreateProcessAsUser(
#         primary_token,
#         exe,
#         command_line,
#         None,
#         None,
#         False,
#         flags,
#         environment,
#         cwd,
#         startup,
#     )

#     print(f"[+] started PID={pid}")

#     thread_handle.Close()
#     process_handle.Close()
#     primary_token.Close()
#     user_token.Close()

#     return pid


# if __name__ == "__main__":
#     enable_privilege("SeAssignPrimaryTokenPrivilege")
#     enable_privilege("SeIncreaseQuotaPrivilege")

#     session_id, domain, username = find_active_session()
#     print(f"[+] active session: {session_id} user={domain}\\{username}")

#     user_token = win32ts.WTSQueryUserToken(session_id)
#     try:
#         # 纯诊断：读 filtered / linked 两个 token 的元数据
#         inspect_linked_token(user_token)
#     finally:
#         user_token.Close()


#     exec, argv = get_exec_and_args()

#     environment = win32profile.CreateEnvironmentBlock(primary_token, False)
#     user_profile = environment.get("USERPROFILE")

#     print(f"[+] target USERPROFILE: {user_profile}")





#     pid = launch_as_logged_on_user(
#         exec,
#         args=argv,
#         require_elevation=True,
#     )

#     # 诊断确认无误后，再决定是否启动：
#     #target_exe = r"C:\windows\system32\cmd.exe"
#     #target_exe = get_executable_path()
#     #pid = launch_as_logged_on_user(target_exe, args=[],
#     #                                require_elevation=True)
#     print(f"PID: {pid}")