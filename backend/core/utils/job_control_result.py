"""Structured results for mutating internal Job controls.

Only Job start/stop/stop_all use this format; status queries retain their
human-readable responses. Do not include Job parameters or source content.
"""
import json


MUTATING_ACTIONS = {'start', 'stop', 'stop_all'}


def encode_job_control_result(action, message, *, job_id='', job_ids=None,
                              total=1, succeeded=1, errors=None):
    return json.dumps({
        'action': action, 'message': str(message),
        'job_id': str(job_id or ''), 'job_ids': list(job_ids or []),
        'total': int(total), 'succeeded': int(succeeded),
        'failed': len(errors or []), 'errors': list(errors or []),
    }, ensure_ascii=False, separators=(',', ':'))


def decode_job_control_result(text, action):
    payload = json.loads(text)
    if not isinstance(payload, dict) or payload.get('action') != action or action not in MUTATING_ACTIONS:
        raise ValueError('Invalid Job control response')
    if not isinstance(payload.get('message'), str) or not isinstance(payload.get('errors'), list):
        raise ValueError('Invalid Job control response')
    if not isinstance(payload.get('total'), int) or not isinstance(payload.get('succeeded'), int) or not isinstance(payload.get('failed'), int):
        raise ValueError('Invalid Job control counts')
    if payload['total'] < 0 or payload['succeeded'] < 0 or payload['failed'] < 0 or payload['succeeded'] + payload['failed'] != payload['total']:
        raise ValueError('Invalid Job control counts')
    return payload
