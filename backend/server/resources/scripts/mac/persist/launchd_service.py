SCRIPT_METADATA = {
    "name": "mac/persistence/launchd_service",
    "display_name": "Manage Launchd Service",
    "description": "Install, start, stop, restart, uninstall, or inspect an RCH LaunchAgent or LaunchDaemon",
    "platforms": ["mac"],
    "category": "Persistence",
    "params": [
        {
            "name": "kind",
            "type": "select",
            "required": False,
            "default": "agent",
            "options": ["agent", "daemon"],
            "description": "Manage a user LaunchAgent or system LaunchDaemon"
        },
        {
            "name": "label",
            "type": "string",
            "required": False,
            "default": "com.rch.client",
            "description": "Unique launchd service label"
        },
        {
            "name": "action",
            "type": "select",
            "required": False,
            "default": "status",
            "options": ["install", "start", "stop", "restart", "uninstall", "status"],
            "description": "Lifecycle action for the launchd service"
        },
        {
            "name": "keep_alive",
            "type": "boolean",
            "required": False,
            "default": True,
            "description": "Set the launchd KeepAlive property"
        },
        {
            "name": "run_at_load",
            "type": "boolean",
            "required": False,
            "default": True,
            "description": "Set RunAtLoad; for LaunchAgents this normally means starting when the user login domain loads the service"
        },
        {
            "name": "scope",
            "type": "select",
            "required": False,
            "default": "user",
            "options": ["user", "global"],
            "description": "LaunchAgent only: install in the target user's Library or /Library/LaunchAgents"
        },
        {
            "name": "target_user",
            "type": "string",
            "required": False,
            "default": "",
            "description": "LaunchAgent only: target macOS user name or UID; leave empty to resolve the current GUI user"
        }
    ]
}

from client.runtime.sdk import launchd


def manage_launchd_service():
    kind = kwargs.get('kind', 'agent')
    result = launchd.manage(
        kind=kind,
        action=kwargs.get('action', 'status'),
        label=kwargs.get('label', launchd.DEFAULT_LAUNCHD_LABEL),
        scope=kwargs.get('scope', 'user') if kind == 'agent' else 'user',
        target_user=(kwargs.get('target_user') or None) if kind == 'agent' else None,
        keep_alive=kwargs.get('keep_alive', True),
        run_at_load=kwargs.get('run_at_load', True),
    )
    print(launchd.format_result(result))


manage_launchd_service()
