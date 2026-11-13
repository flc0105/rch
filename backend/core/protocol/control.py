"""Canonical one-shot Control envelope shared by Server and Clients."""

from dataclasses import dataclass
from enum import Enum


class ExecutionPolicy(str, Enum):
    FOREGROUND = "foreground"
    INDEPENDENT = "independent"


class ClipboardAction(str, Enum):
    GET = "get"
    SET = "set"


class ConfigurationAction(str, Enum):
    GET = "get"
    SET = "set"
    RESET = "reset"


class ProcessAction(str, Enum):
    KILL = "kill"


class WatchdogAction(str, Enum):
    STATUS = "status"


class ControlDomain(str, Enum):
    CLIPBOARD = "clipboard"
    REMOTE_FILES = "remote_files"
    CONFIGURATION = "configuration"
    PROCESS = "process"
    WATCHDOG = "watchdog"


# Shared action metadata: callers cannot select a different scheduling policy.
INDEPENDENT_ACTIONS = frozenset({
    (ControlDomain.CLIPBOARD, ClipboardAction.GET), (ControlDomain.CLIPBOARD, ClipboardAction.SET),
    *((ControlDomain.REMOTE_FILES, action) for action in (
        "browse_directory", "peek_archive", "read_archive_entry", "inspect_upload")),
})


def execution_policy(domain, action):
    return (ExecutionPolicy.INDEPENDENT if (domain, action) in INDEPENDENT_ACTIONS
            else ExecutionPolicy.FOREGROUND)


@dataclass(frozen=True)
class ControlRequest:
    domain: str
    action: str
    payload: dict

    def __post_init__(self):
        validate_control_fields(self.domain, self.action, self.payload)


def validate_control_fields(domain, action, payload):
    if not isinstance(domain, str) or not domain or not isinstance(action, str) or not action:
        raise ValueError('Control domain and action are required')
    if not isinstance(payload, dict):
        raise ValueError('Control payload must be an object')
    return payload


def build_control_message(command_id, domain, action, payload):
    validate_control_fields(domain, action, payload)
    return {
        'type': 'control', 'id': command_id,
        'domain': domain, 'action': action, 'payload': payload,
    }
