"""Job Control requests and canonical semantic results shared by Server/Client."""

from core.protocol.control import JobAction
from core.protocol.references import ReferenceType, entity_reference
from core.utils.command_output import ResultEventType, ResultStatus
from core.protocol.result_envelope import ResultEnvelope

JOB_ACTIONS = frozenset(JobAction)
JOB_MUTATING_ACTIONS = frozenset({JobAction.START, JobAction.STOP, JobAction.STOP_ALL})


def build_job_control_request(action, **parameters):
    if action not in JOB_ACTIONS:
        raise ValueError(f'Unsupported Job control action: {action}')
    return validate_job_control_request(action, parameters)


def validate_job_control_request(action, payload):
    if action not in JOB_ACTIONS or not isinstance(payload, dict):
        raise ValueError('Invalid Job control request')
    expected = {JobAction.START: {'job_name', 'params', 'execution_mode'},
                JobAction.STOP: {'job_key'}, JobAction.STATUS: {'job_key'},
                JobAction.PS: set(), JobAction.STOP_ALL: set()}[action]
    if set(payload) - expected:
        raise ValueError('Unsupported Job control parameters')
    if action == JobAction.START:
        if not isinstance(payload.get('job_name'), str) or not payload['job_name'].strip():
            raise ValueError('Job name is required')
        if not isinstance(payload.get('params', {}), dict):
            raise ValueError('Job parameters must be an object')
        if not isinstance(payload.get('execution_mode'), str) or not payload['execution_mode'].strip():
            raise ValueError('Job execution_mode is required')
    if action in (JobAction.STOP, JobAction.STATUS) and (not isinstance(payload.get('job_key'), str) or not payload['job_key'].strip()):
        raise ValueError('Job key is required')
    return payload


def build_job_control_result(action, message, *, data=None, status='success', job_ids=()):
    """One operation result: display intent belongs to the caller, not the wire."""
    if action not in JOB_ACTIONS:
        raise ValueError('Unsupported Job control action')
    ids = tuple(dict.fromkeys(str(value) for value in job_ids if value))
    references = [entity_reference(ReferenceType.JOB, item) for item in ids]
    result = ResultEnvelope(status=status, message=str(message), data=data,
                            references=references or None).as_payload()
    result['action'] = action
    return validate_job_control_result(result, action)


def validate_job_control_result(payload, action):
    if not isinstance(payload, dict) or action not in JOB_ACTIONS or payload.get('action') != action:
        raise ValueError('Invalid Job control response')
    if payload.get('event_type') != ResultEventType.COMPLETED or payload.get('status') not in ResultStatus._value2member_map_:
        raise ValueError('Invalid Job result status')
    if any(key in payload for key in ('display', 'shape', 'eof')):
        raise ValueError('Unsupported Job result display or transport fields')
    if not isinstance(payload.get('message'), str) or (payload.get('data') is not None and not isinstance(payload['data'], (dict, list))):
        raise ValueError('Invalid Job result content')
    if action in (JobAction.PS, JobAction.STATUS) and payload['status'] == 'success':
        expected = list if action == JobAction.PS else dict
        if not isinstance(payload.get('data'), expected):
            raise ValueError('Structured Job result requires data')
    references = payload.get('references', [])
    if not isinstance(references, list) or any(not isinstance(item, dict) for item in references):
        raise ValueError('Invalid Job references')
    return payload
