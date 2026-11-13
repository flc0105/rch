"""Typed Job Control requests and results shared by Server and Python Client."""

from core.protocol.control import JobAction

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
                JobAction.STOP: {'job_key'}, JobAction.STATUS: {'job_key'}, JobAction.PS: set(), JobAction.STOP_ALL: set()}[action]
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


def build_job_control_result(action, message, *, job_id='', job_ids=None,
                             total=1, succeeded=1, errors=None, **details):
    result = {'action': action, 'message': str(message)}
    if action in JOB_MUTATING_ACTIONS:
        errors = list(errors or [])
        result.update(job_id=str(job_id or ''), job_ids=list(job_ids or []),
                      total=int(total), succeeded=int(succeeded),
                      failed=len(errors), errors=errors)
    result.update(details)
    return result


def validate_job_control_result(payload, action):
    if not isinstance(payload, dict) or payload.get('action') != action or action not in JOB_ACTIONS:
        raise ValueError('Invalid Job control response')
    if not isinstance(payload.get('message'), str):
        raise ValueError('Invalid Job control response')
    if action in JOB_MUTATING_ACTIONS:
        if not isinstance(payload.get('errors'), list) or not all(isinstance(x, str) for x in payload['errors']):
            raise ValueError('Invalid Job control response')
        if not isinstance(payload.get('job_id'), str) or not isinstance(payload.get('job_ids'), list):
            raise ValueError('Invalid Job control response')
        if any(not isinstance(x, str) for x in payload['job_ids']):
            raise ValueError('Invalid Job control response')
        if any(type(payload.get(k)) is not int for k in ('total', 'succeeded', 'failed')):
            raise ValueError('Invalid Job control counts')
        if min(payload['total'], payload['succeeded'], payload['failed']) < 0 or payload['succeeded'] + payload['failed'] != payload['total']:
            raise ValueError('Invalid Job control counts')
    return payload
