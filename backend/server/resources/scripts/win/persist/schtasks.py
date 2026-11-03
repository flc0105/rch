SCRIPT_METADATA = {
    "name": "win/persist/schtasks",
    "display_name": "Scheduled Task Persistence",
    "description": "Create, start, stop, query, or delete a Windows scheduled task",
    "platforms": ["windows"],
    "category": "Persistence",
    "params": [
        {
            "name": "action", "type": "select", "control": "button_group",
            "required": False, "default": "help",
            "options": ["help", "create", "start", "stop", "query", "delete"],
            "description": "Scheduled task operation",
        },
        {
            "name": "name", "type": "string", "required": False,
            "default": "rch", "description": "Scheduled task name",
        },
        {
            "name": "run_as_system", "type": "boolean", "control": "switch",
            "required": False, "default": True,
            "description": "Run as SYSTEM", "visible_when": {"action": "create"},
        },
        {
            "name": "auto_start", "type": "boolean", "control": "switch",
            "required": False, "default": True,
            "description": "Start at user logon", "visible_when": {"action": "create"},
        },
    ],
}

import os
import subprocess

from client.runtime.client_util import get_exec_and_args, get_runtime_root

DEFAULT_NAME = "rch"
TASK_EXECUTABLE, TASK_ARGUMENTS = get_exec_and_args()
TASK_WORKING_DIRECTORY = get_runtime_root()
VALID_ACTIONS = {"help", "create", "start", "stop", "query", "delete"}


def normalize_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off"):
        return False
    raise ValueError("Expected a boolean value for switch")


def run_schtasks(*args):
    return subprocess.run(
        ["schtasks.exe", *args], capture_output=True, text=True, errors="replace"
    )


def create_task(name, run_as_system, auto_start):
    # ScheduledTasks allows a triggerless task that can still be started manually.
    # Environment variables avoid interpolating user-supplied values into PowerShell.
    script = r'''
$ErrorActionPreference = 'Stop'
$actionOptions = @{
    Execute = $env:RCH_TASK_EXE
    WorkingDirectory = $env:RCH_TASK_WORKDIR
}
if (-not [string]::IsNullOrWhiteSpace($env:RCH_TASK_ARGS)) {
    $actionOptions.Argument = $env:RCH_TASK_ARGS
}
$action = New-ScheduledTaskAction @actionOptions
if ($env:RCH_TASK_SYSTEM -eq '1') {
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
} else {
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $principal = New-ScheduledTaskPrincipal -UserId $sid -LogonType Interactive -RunLevel Limited
}
$settings = New-ScheduledTaskSettingsSet
$params = @{
    TaskName = $env:RCH_TASK_NAME
    Action = $action
    Principal = $principal
    Settings = $settings
    Force = $true
}
if ($env:RCH_TASK_AUTOSTART -eq '1') {
    $params.Trigger = New-ScheduledTaskTrigger -AtLogOn
}
Register-ScheduledTask @params | Out-Null
'''
    env = os.environ.copy()
    env.update({
        "RCH_TASK_EXE": TASK_EXECUTABLE,
        "RCH_TASK_ARGS": TASK_ARGUMENTS or "",
        "RCH_TASK_WORKDIR": TASK_WORKING_DIRECTORY,
        "RCH_TASK_NAME": name,
        "RCH_TASK_SYSTEM": "1" if run_as_system else "0",
        "RCH_TASK_AUTOSTART": "1" if auto_start else "0",
    })
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, errors="replace", env=env,
    )


def schtasks(action, name, run_as_system=True, auto_start=True):
    if action not in VALID_ACTIONS:
        print(f'Unknown action: {action}')
        return
    if action == "help":
        print("Scheduled Task Persistence Script")
        print("Actions: help, create, start, stop, query, delete")
        print("Default task name: rch")
        print("Create switches: run_as_system=true, auto_start=true")
        print("start/stop operate on the existing task; switches only affect create")
        return

    if action == "create":
        # Keep the original 'replace existing task' behavior.
        result = create_task(name, run_as_system, auto_start)
        if result.returncode == 0:
            print(f'✓ Scheduled task "{name}" created')
            print(f'  Run as: {"SYSTEM" if run_as_system else "Current user"}')
            print(f'  Trigger: {"At log on" if auto_start else "None (manual only)"}')
            print(f'  Action executable: {TASK_EXECUTABLE}')
            print(f'  Arguments: {TASK_ARGUMENTS or "(none)"}')
            print(f'  Working directory: {TASK_WORKING_DIRECTORY}')
        else:
            print(f'✗ Failed to create scheduled task "{name}": {(result.stderr or result.stdout).strip()}')
        return

    if action == "query":
        result = run_schtasks("/query", "/tn", name)
        if result.returncode:
            print(f'✗ Scheduled task "{name}" does not exist or cannot be queried: {result.stderr.strip()}')
        else:
            print(f'✓ Scheduled task "{name}" exists')
            details = run_schtasks("/query", "/tn", name, "/fo", "LIST")
            print((details.stdout or details.stderr).strip())
        return

    operation = {"delete": "/delete", "start": "/run", "stop": "/end"}[action]
    args = [operation, "/tn", name]
    if action == "delete":
        args.append("/f")
    result = run_schtasks(*args)
    if result.returncode == 0:
        verb = {"delete": "removed", "start": "start requested", "stop": "stop requested"}[action]
        print(f'✓ Scheduled task "{name}": {verb}')
    else:
        print(f'✗ {action} failed for "{name}": {(result.stderr or result.stdout).strip()}')


action = str(kwargs.get("action", "help") or "help").strip().lower()
name = str(kwargs.get("name", DEFAULT_NAME) or DEFAULT_NAME).strip() or DEFAULT_NAME
schtasks(
    action, name,
    normalize_bool(kwargs.get("run_as_system", True)),
    normalize_bool(kwargs.get("auto_start", True)),
)
