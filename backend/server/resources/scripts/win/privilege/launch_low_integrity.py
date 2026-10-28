"""RCH script: diagnose startup of a restricted Low-integrity *client*.

Uses the user/Low/privilege-only token combination that passed the earlier
matrix. Never removes Administrators from the token. Does not modify ACLs,
install persistence, or attach to another process.

In source bundle mode, records a low-token write test and captures RCH's
stdout/stderr in LocalLow. It retains the child process handle long enough
to distinguish a successful CreateProcessAsUser from successful startup.
"""
SCRIPT_METADATA = {
    "name": "win/privilege/launch_low_integrity_diagnostic_v3",
    "display_name": "Launch Low IL (Startup Diagnostic v3)",
    "description": "Check writable Low profile directory, capture RCH startup logs and early exit status with Low IL + trimmed privileges.",
    "platforms": ["win"],
    "category": "Privilege",
    "params": [],
}

import os
import subprocess
import sys
import uuid

import win32api
import win32con
import win32event
import win32process
import win32profile
import win32security
import win32ts

from client.runtime.client_util import get_exec_and_args, get_runtime_root

LOW_SID = "S-1-16-4096"
SYSTEM_SID = "S-1-5-18"
DISABLE_MAX_PRIVILEGE = 0x1
EARLY_EXIT_CHECK_MS = 6000
PROBE_SUCCESS = 37

# This source-bundle-only wrapper executes *the original RCH entrypoint*.
# No code is fetched or imported from the network by this wrapper.
CLIENT_WRAPPER = r'''
import os
import runpy
import sys
import traceback

path = os.environ["RCH_LOW_DIAG_LOG"]
with open(path, "w", encoding="utf-8", buffering=1) as log:
    sys.stdout = log
    sys.stderr = log
    print("[diag] child PID:", os.getpid(), flush=True)
    print("[diag] Python:", sys.executable, flush=True)
    print("[diag] TEMP:", os.environ.get("TEMP"), flush=True)
    if len(sys.argv) < 2:
        raise RuntimeError("Missing original RCH entrypoint")
    entrypoint = os.path.abspath(sys.argv[1])
    entry_args = sys.argv[2:]
    print("[diag] entrypoint:", entrypoint, flush=True)
    print("[diag] original args:", repr(entry_args), flush=True)
    sys.argv = [entrypoint] + entry_args
    if os.path.dirname(entrypoint) not in sys.path:
        sys.path.insert(0, os.path.dirname(entrypoint))
    try:
        runpy.run_path(entrypoint, run_name="__main__")
    except BaseException:
        print("[diag] UNHANDLED EXCEPTION:", flush=True)
        traceback.print_exc()
        raise
    print("[diag] RCH entrypoint returned (possibly after catching an error)", flush=True)
'''


def _is_system():
    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid, _ = win32security.GetTokenInformation(token, win32security.TokenUser)
        return win32security.ConvertSidToStringSid(sid) == SYSTEM_SID
    finally:
        token.Close()


def _enable_privilege(name):
    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(),
        win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY)
    try:
        luid = win32security.LookupPrivilegeValue(None, name)
        win32security.AdjustTokenPrivileges(
            token, False, [(luid, win32con.SE_PRIVILEGE_ENABLED)])
        if win32api.GetLastError() == 1300:
            raise RuntimeError("Missing privilege: " + name)
    finally:
        token.Close()


def _get_user_primary_token():
    if _is_system():
        for privilege in ("SeAssignPrimaryTokenPrivilege", "SeIncreaseQuotaPrivilege"):
            _enable_privilege(privilege)
        sessions = []
        for item in win32ts.WTSEnumerateSessions(
                win32ts.WTS_CURRENT_SERVER_HANDLE, 1, 0):
            if item["State"] != win32ts.WTSActive:
                continue
            session_id = item["SessionId"]
            user = win32ts.WTSQuerySessionInformation(
                win32ts.WTS_CURRENT_SERVER_HANDLE, session_id, win32ts.WTSUserName)
            if user:
                sessions.append((session_id, user))
        if len(sessions) != 1:
            raise RuntimeError("Expected one active interactive user session: %r" % sessions)
        print("[+] Using interactive session: %r" % (sessions[0],))
        source = win32ts.WTSQueryUserToken(sessions[0][0])
    else:
        print("[+] Using current user's token")
        source = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(), win32con.MAXIMUM_ALLOWED)
    try:
        return win32security.DuplicateTokenEx(
            source, win32security.SecurityImpersonation,
            win32con.MAXIMUM_ALLOWED, win32security.TokenPrimary, None)
    finally:
        source.Close()


def _create_low_token(primary):
    # This exactly matches 'low_plus_privileges' from the successful matrix.
    low = win32security.CreateRestrictedToken(
        primary, DISABLE_MAX_PRIVILEGE, [], [], [])
    try:
        win32security.SetTokenInformation(
            low, win32security.TokenIntegrityLevel,
            (win32security.ConvertStringSidToSid(LOW_SID), 0x60))
        actual, _ = win32security.GetTokenInformation(
            low, win32security.TokenIntegrityLevel)
        if win32security.ConvertSidToStringSid(actual) != LOW_SID:
            raise RuntimeError("Low IL not applied")
        return low
    except BaseException:
        low.Close()
        raise


def _create_process(token, executable, cmdline, env, cwd, wait_ms):
    startup = win32process.STARTUPINFO()
    startup.lpDesktop = None
    process, thread, pid, _ = win32process.CreateProcessAsUser(
        token, executable, cmdline, None, None, False,
        win32con.CREATE_UNICODE_ENVIRONMENT | win32con.CREATE_NO_WINDOW,
        env, cwd, startup)
    try:
        status = win32event.WaitForSingleObject(process, wait_ms)
        if status == win32event.WAIT_OBJECT_0:
            code = win32process.GetExitCodeProcess(process)
            return pid, code, "exited"
        if status == win32event.WAIT_TIMEOUT:
            return pid, None, "running"
        return pid, None, "unknown wait result %r" % status
    finally:
        thread.Close()
        process.Close()


def _show_log(path, max_chars=13000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        print("\n----- DIAGNOSTIC LOG (tail) -----")
        print(text[-max_chars:] or "<empty>")
        print("----- END LOG -----\n")
    except OSError as e:
        print("[!] Could not read diagnostic log %s: %s" % (path, e))


def main():
    if getattr(sys, "frozen", False):
        raise RuntimeError("This diagnostic wrapper supports RCH Python source bundles only")
    executable, _args_text = get_exec_and_args()
    executable = os.path.realpath(executable)
    cwd = os.path.realpath(get_runtime_root())
    entrypoint = os.path.realpath(sys.argv[0])
    if not os.path.isfile(entrypoint):
        raise FileNotFoundError("RCH entrypoint not found: " + entrypoint)
    if os.path.basename(entrypoint).lower() != "rchclient.py":
        raise RuntimeError("Expected to run from rchclient.py: " + entrypoint)

    primary = _get_user_primary_token()
    try:
        env = dict(win32profile.CreateEnvironmentBlock(primary, False))
        userprofile = env.get("USERPROFILE") or os.path.expanduser("~")
        diagnostics_dir = os.path.join(
            userprofile, "AppData", "LocalLow", "RCHLowDiagnostics")
        temp_dir = os.path.join(diagnostics_dir, "tmp")
        # These are created by the parent. The low child must still pass
        # both the MIC check and the DACL check before it can write here.
        os.makedirs(temp_dir, exist_ok=True)
        nonce = uuid.uuid4().hex[:10]
        probe_log = os.path.join(diagnostics_dir, "write_probe-" + nonce + ".txt")
        rch_log = os.path.join(diagnostics_dir, "rch_start-" + nonce + ".log")
        env.update({
            "TEMP": temp_dir,
            "TMP": temp_dir,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "RCH_LOW_DIAG_PROBE": probe_log,
            "RCH_LOW_DIAG_LOG": rch_log,
        })
        print("[+] Python:", executable)
        print("[+] Entry:", entrypoint)
        print("[+] cwd:", cwd)
        print("[+] Low diagnostics directory:", diagnostics_dir)
        token = _create_low_token(primary)
        try:
            # First check whether a Low child can write *any* diagnostic file.
            probe_script = (
                "import os,sys; "
                "p=os.environ['RCH_LOW_DIAG_PROBE']; "
                "f=open(p,'w',encoding='utf-8'); "
                "f.write('low child can write here\\n');f.close();"
                "sys.exit(37)"
            )
            probe_cmd = subprocess.list2cmdline([executable, "-c", probe_script])
            probe_pid, probe_exit, probe_state = _create_process(
                token, executable, probe_cmd, env, cwd, 4000)
            print("[+] Write probe PID=%d status=%s exit=%s" % (
                probe_pid, probe_state, probe_exit))
            if probe_state != "exited" or probe_exit != PROBE_SUCCESS:
                print("[-] Low-token child cannot finish the LocalLow write probe.")
                print("[-] Inspect directory integrity/DACL, without modifying system folders:")
                print('    icacls "%s"' % diagnostics_dir)
                return

            rch_cmd = subprocess.list2cmdline(
                [executable, "-u", "-c", CLIENT_WRAPPER,
                 entrypoint] + list(sys.argv[1:]))
            pid, code, state = _create_process(
                token, executable, rch_cmd, env, cwd, EARLY_EXIT_CHECK_MS)
            print("[+] RCH child PID=%d status=%s" % (pid, state))
            if state == "exited":
                print("[-] RCH child exit=%s (0x%08X)" % (code, code & 0xffffffff))
            elif state == "running":
                print("[+] Child still running after %.1f seconds; check server session" % (
                    EARLY_EXIT_CHECK_MS / 1000))
            print("[+] RCH diagnostic log:", rch_log)
            _show_log(rch_log)
            print("[!] Log may contain server addresses and task details; redact before sharing.")
        finally:
            token.Close()
    finally:
        primary.Close()


if __name__ == "__main__":
    main()
