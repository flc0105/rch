"""Job Control requests and canonical semantic results shared by Server/Client."""

from core.protocol.control import JobAction
from core.protocol.references import ReferenceType, entity_reference
from core.utils.command_output import ResultDisplay, ResultDataShape, ResultEventType
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


def build_job_control_result(action, message, *, data=None, status='success', display=ResultDisplay.MESSAGE,
                             shape=None, width=None, job_ids=()):
    """One business payload, with explicit presentation intent and optional Job links."""
    if action not in JOB_ACTIONS:
        raise ValueError('Unsupported Job control action')
    result = ResultEnvelope(status=status, message=str(message), data=data, display=display,
                            shape=ResultDataShape(shape) if shape else None).as_payload()
    result['action'] = action
    if display == ResultDisplay.DATA and isinstance(data, dict):
        result['width'] = width or 20
    ids = tuple(dict.fromkeys(str(value) for value in job_ids if value))
    if ids:
        result['references'] = [entity_reference(ReferenceType.JOB, item) for item in ids]
    return validate_job_control_result(result, action)


def validate_job_control_result(payload, action):
    if not isinstance(payload, dict) or action not in JOB_ACTIONS or payload.get('action') != action:
        raise ValueError('Invalid Job control response')
    if payload.get('event_type') != ResultEventType.COMPLETED or payload.get('status') not in ('success', 'error'):
        raise ValueError('Invalid Job result status')
    if payload.get('display') not in (ResultDisplay.MESSAGE, ResultDisplay.DATA):
        raise ValueError('Invalid Job result display')
    if not isinstance(payload.get('message'), str) or (payload.get('data') is not None and not isinstance(payload['data'], (dict, list))):
        raise ValueError('Invalid Job result content')
    if payload['display'] == ResultDisplay.DATA and payload['status'] == 'success':
        if not isinstance(payload.get('data'), (dict, list)):
            raise ValueError('Structured Job result requires data')
        if payload.get('shape') not in (ResultDataShape.FLAT, ResultDataShape.TABLE):
            raise ValueError('Invalid Job data shape')
        if isinstance(payload['data'], dict) and (type(payload.get('width')) is not int or payload['width'] <= 0):
            raise ValueError('Invalid Job data width')
    references = payload.get('references', [])
    if not isinstance(references, list) or any(not isinstance(item, dict) for item in references):
        raise ValueError('Invalid Job references')
    return payload
