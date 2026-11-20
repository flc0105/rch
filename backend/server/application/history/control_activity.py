"""Recording policy for the shared Control contract."""
from copy import deepcopy

from core.protocol.control import ActivityPolicy, ControlDomain, RemoteFilesAction, ScriptAction, action_spec
from core.protocol.message_types import MSG_TYPE_CONTROL
from server.config import config


# These fields are required by the receiver, but are omitted from History.
# Match the exact Control action and only the top level of its payload.
OMIT_RESOLVED_PAYLOAD = {
    (ControlDomain.REMOTE_FILES, RemoteFilesAction.SAVE_FILE): {'content'},
    (ControlDomain.SCRIPT, ScriptAction.RUN): {'source'},
}


def should_record(domain, action):
    return (action_spec(domain, action).activity == ActivityPolicy.ALWAYS
            or bool(getattr(config, 'RECORD_OPTIONAL_ACTIVITY', False)))

def resolved_snapshot(request):
    """Copy the sent request for Activity without copying excluded bodies."""
    if request.get('type') == MSG_TYPE_CONTROL:
        omitted = OMIT_RESOLVED_PAYLOAD.get((request['domain'], request['action']))
        if omitted:
            payload = {key: value for key, value in request['payload'].items() if key not in omitted}
            return deepcopy({**request, 'payload': payload})
    return deepcopy(request)
