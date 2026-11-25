"""Small UDP datagram contract for LAN Bind service discovery."""
import json

DISCOVERY_PORT = 19449
SERVICE = 'rch-bind'


def read_packet(packet):
    if not isinstance(packet, bytes) or len(packet) > 1024:
        return None
    try:
        value = json.loads(packet.decode('utf-8'))
    except (ValueError, UnicodeError):
        return None
    if not isinstance(value, dict) or value.get('service') != SERVICE:
        return None
    nonce = value.get('nonce')
    if not isinstance(nonce, str) or len(nonce) != 16 or any(c not in '0123456789abcdef' for c in nonce):
        return None
    return value


def make_packet(**fields):
    return json.dumps({'service': SERVICE, **fields}, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
