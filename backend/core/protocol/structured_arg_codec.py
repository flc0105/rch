import base64
import json


JSON_PREFIX = '__json__:'


def strip_wrapped_quotes(value: str) -> str:
    text = (value or '').strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        return text[1:-1]
    return text


def encode_structured_arg(payload) -> str:
    raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    encoded = base64.urlsafe_b64encode(raw).decode('utf-8')
    return f'{JSON_PREFIX}{encoded}'


def decode_structured_arg(raw, *, require_prefix: bool = False):
    text = strip_wrapped_quotes(raw)
    if not text:
        if require_prefix:
            raise ValueError('Structured argument is required')
        return ''

    if text.startswith(JSON_PREFIX):
        encoded = text[len(JSON_PREFIX):]
        decoded = base64.urlsafe_b64decode(encoded.encode()).decode('utf-8')
        return json.loads(decoded)

    if require_prefix:
        raise ValueError(f'Structured argument must start with {JSON_PREFIX}')
    return text


class StructuredArgCodec:
    """Shared structured command-argument codec."""

    JSON_PREFIX = JSON_PREFIX

    @staticmethod
    def strip_wrapped_quotes(value: str) -> str:
        return strip_wrapped_quotes(value)

    @staticmethod
    def encode(payload) -> str:
        return encode_structured_arg(payload)

    @staticmethod
    def decode(raw):
        return decode_structured_arg(raw)

    def extract_path(self, raw) -> str:
        value = self.decode(raw)
        if isinstance(value, dict):
            return (value.get('path') or '').strip()
        return (value or '').strip()
