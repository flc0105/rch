"""Canonical one-shot Control envelope shared by Server and Clients."""

from dataclasses import dataclass
from enum import Enum
from core.protocol.message_types import MSG_TYPE_CONTROL


class ControlValue(str, Enum):
    """String-valued wire identifiers; formatting must preserve the wire value."""

    def __str__(self):
        return self.value


class ExecutionPolicy(ControlValue):
    FOREGROUND = "foreground"
    INDEPENDENT = "independent"


class ControlDomain(ControlValue):
    JOB = "job"
    REMOTE_FILES = "remote_files"
    SCRIPT = "script"
    CLIPBOARD = "clipboard"
    CONFIGURATION = "configuration"
    PROCESS = "process"
    WATCHDOG = "watchdog"


class JobAction(ControlValue):
    START = "start"
    STOP = "stop"
    STOP_ALL = "stop_all"
    PS = "ps"
    STATUS = "status"


class RemoteFilesAction(ControlValue):
    BROWSE_DIRECTORY = "browse_directory"
    CREATE_DIRECTORY = "create_directory"
    RENAME_PATH = "rename_path"
    DELETE_PATHS = "delete_paths"
    PASTE_PATHS = "paste_paths"
    CREATE_ARCHIVE = "create_archive"
    PEEK_ARCHIVE = "peek_archive"
    READ_ARCHIVE_ENTRY = "read_archive_entry"
    EXTRACT_ARCHIVE = "extract_archive"
    INSPECT_UPLOAD = "inspect_upload"
    SAVE_FILE = "save_file"


class ScriptAction(ControlValue):
    RUN = "run"


class ClipboardAction(ControlValue):
    GET = "get"
    SET = "set"


class ConfigurationAction(ControlValue):
    GET = "get"
    SET = "set"
    RESET = "reset"


class ProcessAction(ControlValue):
    KILL = "kill"


class WatchdogAction(ControlValue):
    STATUS = "status"


# Canonical protocol catalog: the Server and Client share the same action policy.
# This describes the wire contract, not how a Manager executes an action.
_CONTROL_ACTIONS = {
    ControlDomain.JOB: dict.fromkeys(JobAction, ExecutionPolicy.FOREGROUND),
    ControlDomain.REMOTE_FILES: {
        **dict.fromkeys(RemoteFilesAction, ExecutionPolicy.FOREGROUND),
        RemoteFilesAction.BROWSE_DIRECTORY: ExecutionPolicy.INDEPENDENT,
        RemoteFilesAction.PEEK_ARCHIVE: ExecutionPolicy.INDEPENDENT,
        RemoteFilesAction.READ_ARCHIVE_ENTRY: ExecutionPolicy.INDEPENDENT,
        RemoteFilesAction.INSPECT_UPLOAD: ExecutionPolicy.INDEPENDENT,
    },
    ControlDomain.SCRIPT: dict.fromkeys(ScriptAction, ExecutionPolicy.FOREGROUND),
    ControlDomain.CLIPBOARD: dict.fromkeys(ClipboardAction, ExecutionPolicy.INDEPENDENT),
    ControlDomain.CONFIGURATION: dict.fromkeys(ConfigurationAction, ExecutionPolicy.FOREGROUND),
    ControlDomain.PROCESS: dict.fromkeys(ProcessAction, ExecutionPolicy.FOREGROUND),
    ControlDomain.WATCHDOG: dict.fromkeys(WatchdogAction, ExecutionPolicy.FOREGROUND),
}


def control_actions(domain):
    """Return the declared action/policy pairs for a domain."""
    return tuple(_CONTROL_ACTIONS[domain].items())


def execution_policy(domain, action):
    # Unknown requests use the normal lane and receive an unsupported-action result.
    return _CONTROL_ACTIONS.get(domain, {}).get(action, ExecutionPolicy.FOREGROUND)


@dataclass(frozen=True)
class ControlRequest:
    domain: ControlDomain
    action: ControlValue
    payload: dict

    def __post_init__(self):
        validate_control_fields(self.domain, self.action, self.payload)
        domain = ControlDomain(self.domain)
        action = next((item for item, _ in control_actions(domain) if item == self.action), None)
        if action is None:
            raise ValueError(f'Unsupported Control action: {domain}/{self.action}')
        object.__setattr__(self, 'domain', domain)
        object.__setattr__(self, 'action', action)


def validate_control_fields(domain, action, payload):
    if not isinstance(domain, str) or not domain or not isinstance(action, str) or not action:
        raise ValueError('Control domain and action are required')
    if not isinstance(payload, dict):
        raise ValueError('Control payload must be an object')
    return payload


def build_control_message(command_id, domain, action, payload):
    validate_control_fields(domain, action, payload)
    return {
        'type': MSG_TYPE_CONTROL, 'id': command_id,
        'domain': str(domain), 'action': str(action), 'payload': payload,
    }
