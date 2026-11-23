import json

from flask import request


# ------------------ request helpers ------------------ #
def get_json_payload():
    return request.get_json(silent=True) or {}


def get_required_command():
    payload = get_json_payload()
    command = (payload.get('command') or '').strip()
    if not command:
        raise ValueError('command is required')
    return command


def get_required_upload():
    upload = request.files.get('file')
    if not upload or not upload.filename:
        raise ValueError('file is required')
    return upload


def get_optional_remote_path():
    return (request.args.get('path') or '').strip()


def get_optional_form_text(name: str, default: str = '') -> str:
    return (request.form.get(name) or default).strip()


def get_optional_header_text(name: str, default: str = '') -> str:
    return (request.headers.get(name) or default).strip()


def get_optional_tab_id() -> str:
    return get_optional_header_text('X-Tab-Id', '')


def parse_optional_json_form(name: str) -> dict:
    raw = (request.form.get(name) or '').strip()
    if not raw:
        return {}

    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    return {}


def parse_optional_int_form(name: str):
    raw = (request.form.get(name) or '').strip()
    if not raw:
        return None

    try:
        return int(raw)
    except Exception:
        return None


def parse_paging_args(default_page=1, default_page_size=100):
    page_raw = (request.args.get('page') or '').strip()
    page_size_raw = (request.args.get('page_size') or '').strip()
    show_hidden_raw = (request.args.get('show_hidden') or '').strip().lower()

    try:
        page = int(page_raw) if page_raw else default_page
    except Exception:
        page = default_page

    try:
        page_size = int(page_size_raw) if page_size_raw else default_page_size
    except Exception:
        page_size = default_page_size

    return {
        'page': page,
        'page_size': page_size,
        'show_hidden': show_hidden_raw in ('1', 'true', 'yes', 'on'),
    }


def get_pagination(default_limit: int = 20, max_limit: int = 100) -> tuple[int, int]:
    """Validate bounded SQL page size and non-negative offset at the web boundary."""
    from flask import request
    try:
        limit = int(request.args.get('limit', default_limit))
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid pagination parameters') from exc
    if not 1 <= limit <= max_limit or offset < 0:
        raise ValueError('Invalid pagination parameters')
    return limit, offset
