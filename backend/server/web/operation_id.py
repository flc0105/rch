"""Read the browser operation correlation ID for Web task submissions."""

import uuid
from flask import request


def get_optional_operation_id():
    raw = str(request.headers.get('X-RCH-Operation-ID') or '').strip()
    if not raw:
        return ''
    if len(raw) > 64:
        raise ValueError('Invalid operation ID')
    try:
        normalized = str(uuid.UUID(raw))
    except (ValueError, AttributeError) as exc:
        raise ValueError('Invalid operation ID') from exc
    if normalized != raw.lower():
        raise ValueError('Invalid operation ID')
    return normalized
