"""Reversible login payload masking for UI transport; this is not transport security."""

import base64
import binascii


_MASK_KEY = b'RCH-login-transport-mask'


def decode_masked_password(payload):
    """Undo the browser's small XOR mask without accepting a plaintext field."""
    if not isinstance(payload, dict):
        raise ValueError('Invalid login request')
    encoded = payload.get('masked_password')
    encoded_nonce = payload.get('mask_nonce')
    if not isinstance(encoded, str) or not 1 <= len(encoded) <= 8192:
        raise ValueError('Invalid login request')
    if not isinstance(encoded_nonce, str) or len(encoded_nonce) != 24:
        raise ValueError('Invalid login request')
    try:
        masked = base64.b64decode(encoded, validate=True)
        nonce = base64.b64decode(encoded_nonce, validate=True)
        if len(nonce) != 16 or not 1 <= len(masked) <= 4096:
            raise ValueError('Invalid login request')
        password_bytes = bytes(
            value ^ _MASK_KEY[index % len(_MASK_KEY)] ^ nonce[index % len(nonce)]
            for index, value in enumerate(masked)
        )
        return password_bytes.decode('utf-8')
    except (UnicodeDecodeError, ValueError, binascii.Error) as exc:
        raise ValueError('Invalid login request') from exc
