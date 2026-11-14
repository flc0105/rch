"""Browser-origin validation for the HTTP and same-origin WS proxy paths."""

from urllib.parse import urlsplit


def websocket_origin_allowed(origin: str, host: str, web_port: int) -> bool:
    try:
        browser = urlsplit(origin)
        request = urlsplit('http://' + host)
        if browser.scheme not in ('http', 'https') or not browser.hostname or not request.hostname:
            return False
        if browser.hostname.casefold() != request.hostname.casefold():
            return False
        browser_port, request_port = browser.port, request.port
    except ValueError:
        return False
    # Local production UI is served on WEB_PORT and its WS port is WEB_PORT+1.
    # Vite/reverse proxies forward /ws on the *browser-facing* Host/port, which
    # can differ from the local dev port (e.g. FRP 15173 -> Vite 5173).
    return (browser_port == request_port or
            (browser_port in (web_port, None) and request_port == web_port + 1))
