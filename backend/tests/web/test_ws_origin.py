"""WebSocket origin validation for local and single-port reverse-proxy setups."""
from server.web.ws_origin import websocket_origin_allowed


def test_vite_forwarded_over_public_frp_port():
    assert websocket_origin_allowed('http://example.test:15173', 'example.test:15173', 8085)
    assert websocket_origin_allowed('https://example.test:15173', 'example.test:15173', 8085)
    assert websocket_origin_allowed('http://localhost:5173', 'localhost:5173', 8085)


def test_production_web_and_ws_ports():
    assert websocket_origin_allowed('http://localhost:8085', 'localhost:8086', 8085)
    assert websocket_origin_allowed('https://example.test', 'example.test:8086', 8085)


def test_other_origins_and_ports_are_rejected():
    assert not websocket_origin_allowed('http://evil.test:15173', 'example.test:15173', 8085)
    assert not websocket_origin_allowed('http://example.test:15173', 'example.test:8086', 8085)
    assert not websocket_origin_allowed('file:///etc/passwd', 'example.test:15173', 8085)
    assert not websocket_origin_allowed('http://example.test:bad', 'example.test:15173', 8085)
