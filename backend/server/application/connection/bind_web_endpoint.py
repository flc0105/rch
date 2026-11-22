"""Server-announced Web API origin for a Bind connection."""
from urllib.parse import urlsplit


def validate_web_origin(value: str) -> str:
    url = str(value or '').strip().rstrip('/')
    parsed = urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
            or parsed.password or parsed.path or parsed.query or parsed.fragment
            or any(ch.isspace() for ch in url)):
        raise ValueError('Server Web URL must be a valid http(s) origin')
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError('Invalid Server Web URL port') from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError('Invalid Server Web URL port')
    return url


def default_bind_web_url(request_origin: str = '') -> str:
    """Explicit deployment setting takes priority over the Web request origin."""
    from server.config.config import WEB_ADVERTISED_BASE_URL
    return validate_web_origin(WEB_ADVERTISED_BASE_URL or request_origin)
