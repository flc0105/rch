"""Explicit references to persisted entities carried by business results."""
from enum import Enum


class ReferenceType(str, Enum):
    ARTIFACT = 'artifact'
    JOB = 'job'


def entity_reference(kind, identifier):
    kind = ReferenceType(kind)
    if not isinstance(identifier, str) or not identifier:
        raise ValueError('Reference ID is required')
    return {'type': kind.value, 'id': identifier}


LOG_FILE_REFERENCE_TYPE = 'log_file'
SESSION_ACTION_REFERENCE_TYPE = 'session_action'


def log_file_reference(path: str, *, title: str = 'Client startup') -> dict:
    """Reference to a Client-side log readable with the existing Log Viewer."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError('Log file path is required')
    return {'type': LOG_FILE_REFERENCE_TYPE, 'path': path, 'title': title}


def session_action_reference(action: str) -> dict:
    """Reference to an explicit action on the originating Client Session."""
    if action != 'kill_instance':
        raise ValueError('Unsupported session action')
    return {'type': SESSION_ACTION_REFERENCE_TYPE, 'action': action}
