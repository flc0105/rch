"""macOS launchd service management for Client scripts."""

from client.runtime.launchd_service_manager import (
    DEFAULT_LAUNCHD_LABEL,
    VALID_LAUNCHD_ACTIONS,
    format_launchd_service_result,
    manage_launchd_service,
)


def manage(*, kind: str, action: str, label: str = DEFAULT_LAUNCHD_LABEL,
           scope: str = 'user', target_user=None, keep_alive: bool = True,
           run_at_load: bool = True, command: str = '',
           working_directory: str = '') -> dict:
    return manage_launchd_service(
        kind=kind,
        action=action,
        label=label,
        scope=scope,
        target_user=target_user,
        keep_alive=keep_alive,
        run_at_load=run_at_load,
        command=command,
        working_directory=working_directory,
    )


def format_result(result: dict) -> str:
    return format_launchd_service_result(result)


__all__ = [
    'DEFAULT_LAUNCHD_LABEL',
    'VALID_LAUNCHD_ACTIONS',
    'manage',
    'format_result',
]
