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
