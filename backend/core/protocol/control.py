"""Canonical one-shot Control envelope shared by Server and Clients."""

from dataclasses import dataclass


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
