"""Opt-in Web interaction for Client inproc scripts; never uses shell stdin."""
from client.http.client_api import ClientApiClient
from client.runtime.sdk import context


class ScriptSdkInteractionError(RuntimeError):
    pass


def _request(kind, message, *, title='', timeout=90, placeholder='', options=None, preview=None):
    if not context.get_script_grant_token():
        raise ScriptSdkInteractionError(
            'Interaction requires SCRIPT_METADATA api_grants: ["interactions:request"]'
        )
    if context.get_command_id() is None:
        raise ScriptSdkInteractionError('Interaction requires a running Client script command')
    timeout = max(1, min(int(timeout), 180))
    data = ClientApiClient().post_data(
        '/api/interactions/client/request',
        json={'kind': kind, 'title': str(title), 'message': str(message),
              'placeholder': str(placeholder), 'timeout_seconds': timeout,
              'options': options if options is not None else [], 'preview': preview},
        timeout=timeout + 15,
    )
    if not isinstance(data, dict):
        raise ScriptSdkInteractionError('Invalid interaction response')
    return data


def confirm(message: str, *, title='Confirmation', timeout=90) -> bool:
    """Return True only after explicit approval. Rejection/timeout always False."""
    result = _request('confirm', message, title=title, timeout=timeout)
    return result.get('status') == 'answered' and result.get('value') is True


def ask(message: str, *, title='Input required', timeout=90, placeholder='', secret=False) -> str:
    """Wait for a text answer, raising if rejected/expired/cancelled."""
    result = _request('secret' if secret else 'input', message, title=title,
                      timeout=timeout, placeholder=placeholder)
    if result.get('status') != 'answered' or not isinstance(result.get('value'), str):
        raise ScriptSdkInteractionError(f'Input was not supplied ({result.get("status")})')
    return result['value']


def select(message: str, options, *, title='Choose an option', timeout=90) -> str:
    """Select one explicitly offered value; rejection/timeout raises."""
    result = _request('select', message, title=title, timeout=timeout, options=list(options))
    if result.get('status') != 'answered' or result.get('value') not in options:
        raise ScriptSdkInteractionError(f'Selection not supplied ({result.get("status")})')
    return result['value']


def approve_preview(message: str, preview: dict, *, title='Review execution plan', timeout=90) -> bool:
    """Approve a plain-data preview (summary, columns/rows, collapsible details)."""
    result = _request('preview', message, title=title, timeout=timeout, preview=preview)
    return result.get('status') == 'answered' and result.get('value') is True
