"""Launch an RCH Client with Low integrity and restricted privileges.

Uses the interactive user's token when invoked as SYSTEM, or the current
user's token otherwise. Logs the startup steps and Client output in LocalLow.
"""
SCRIPT_METADATA = {
    "name": "win/privilege/launch_low_integrity",
    "display_name": "Launch Low Integrity Client",
    "description": "Launch an RCH Client with Low integrity and restricted privileges.",
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

# Execute the original source entrypoint and retain its output in a per-launch log.
CLIENT_WRAPPER = r'''
import os
import runpy
import sys
import traceback

path = os.environ["RCH_LOW_LOG"]
with open(path, "w", encoding="utf-8", buffering=1) as log:
    sys.stdout = log
    sys.stderr = log
    print("Client PID:", os.getpid(), flush=True)
    print("Python:", sys.executable, flush=True)
    print("TEMP:", os.environ.get("TEMP"), flush=True)
    if len(sys.argv) < 2:
        raise RuntimeError("Missing original RCH entrypoint")
    entrypoint = os.path.abspath(sys.argv[1])
    entry_args = sys.argv[2:]
    print("Entrypoint:", entrypoint, flush=True)
    print("Arguments:", repr(entry_args), flush=True)
    sys.argv = [entrypoint] + entry_args
    if os.path.dirname(entrypoint) not in sys.path:
        sys.path.insert(0, os.path.dirname(entrypoint))
    try:
        runpy.run_path(entrypoint, run_name="__main__")
    except BaseException:
        print("Unhandled Client exception:", flush=True)
        traceback.print_exc()
        raise
    print("RCH entrypoint returned", flush=True)
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
        print("\n----- CLIENT LOG (tail) -----", flush=True)
        print(text[-max_chars:] or "<empty>", flush=True)
        print("----- END CLIENT LOG -----\n", flush=True)
    except OSError as e:
        print("[!] Could not read Client log %s: %s" % (path, e), flush=True)


def main():
    print("[1/5] Validating RCH entrypoint", flush=True)
    if getattr(sys, "frozen", False):
        raise RuntimeError("Low Integrity Client launch supports RCH Python source bundles only")
    executable, _args_text = get_exec_and_args()
    executable = os.path.realpath(executable)
    cwd = os.path.realpath(get_runtime_root())
    entrypoint = os.path.realpath(sys.argv[0])
    if not os.path.isfile(entrypoint):
        raise FileNotFoundError("RCH entrypoint not found: " + entrypoint)
    if os.path.basename(entrypoint).lower() != "rchclient.py":
        raise RuntimeError("Expected to run from rchclient.py: " + entrypoint)

    print("      Python:", executable, flush=True)
    print("      Entrypoint:", entrypoint, flush=True)
    print("      Working directory:", cwd, flush=True)
    print("[2/5] Acquiring user token", flush=True)
    primary = _get_user_primary_token()
    try:
        print("      User token acquired", flush=True)
        print("[3/5] Preparing Client environment and logs", flush=True)
        env = dict(win32profile.CreateEnvironmentBlock(primary, False))
        userprofile = env.get("USERPROFILE") or os.path.expanduser("~")
        log_dir = os.path.join(
            userprofile, "AppData", "LocalLow", "RCHLowClient")
        temp_dir = os.path.join(log_dir, "tmp")
        # These are created by the parent. The low child must still pass
        # both the MIC check and the DACL check before it can write here.
        os.makedirs(temp_dir, exist_ok=True)
        nonce = uuid.uuid4().hex[:10]
        probe_log = os.path.join(log_dir, "write_check-" + nonce + ".txt")
        rch_log = os.path.join(log_dir, "rch_client-" + nonce + ".log")
        env.update({
            "TEMP": temp_dir,
            "TMP": temp_dir,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "RCH_LOW_WRITE_CHECK": probe_log,
            "RCH_LOW_LOG": rch_log,
        })
        print("      Client log directory:", log_dir, flush=True)
        print("      Log file:", rch_log, flush=True)
        print("[4/5] Creating Low Integrity token and checking log write access", flush=True)
        token = _create_low_token(primary)
        try:
            print("      Low Integrity token created", flush=True)
            # Verify the actual Low Integrity child can write to its log directory.
            probe_script = (
                "import os,sys; "
                "p=os.environ['RCH_LOW_WRITE_CHECK']; "
                "f=open(p,'w',encoding='utf-8'); "
                "f.write('Low Integrity write check passed\\n');f.close();"
                "sys.exit(37)"
            )
            probe_cmd = subprocess.list2cmdline([executable, "-c", probe_script])
            probe_pid, probe_exit, probe_state = _create_process(
                token, executable, probe_cmd, env, cwd, 4000)
            print("      Write check PID=%d status=%s exit=%s" % (
                probe_pid, probe_state, probe_exit), flush=True)
            if probe_state != "exited" or probe_exit != PROBE_SUCCESS:
                print("[FAILED] Low Integrity child cannot write to the Client log directory.", flush=True)
                print("         Inspect directory integrity and access permissions:", flush=True)
                print('         icacls "%s"' % log_dir, flush=True)
                return
            print("      Log write check passed", flush=True)

            print("[5/5] Starting RCH Client and checking early exit", flush=True)
            rch_cmd = subprocess.list2cmdline(
                [executable, "-u", "-c", CLIENT_WRAPPER,
                 entrypoint] + list(sys.argv[1:]))
            pid, code, state = _create_process(
                token, executable, rch_cmd, env, cwd, EARLY_EXIT_CHECK_MS)
            print("      Client PID=%d status=%s" % (pid, state), flush=True)
            if state == "exited":
                print("[FAILED] Client exited during startup: code=%s (0x%08X)" % (
                    code, code & 0xffffffff), flush=True)
            elif state == "running":
                print("[OK] Client still running after %.1f seconds; check the Server session" % (
                    EARLY_EXIT_CHECK_MS / 1000), flush=True)
            else:
                print("[!] Client wait status: %s" % state, flush=True)
            print("      Client log:", rch_log, flush=True)
            _show_log(rch_log)
            print("[!] Logs may contain server addresses and task details; review before sharing.", flush=True)
        finally:
            token.Close()
    finally:
        primary.Close()


if __name__ == "__main__":
    main()