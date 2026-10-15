"""Interaction Broker access for ordinary Client commands with active grants."""


class CommandInteractionError(RuntimeError):
    pass


class CommandInteractions:
    """Use the active, command-bound interaction grant; never submit a new Command."""

    def __init__(self, owner):
        self.owner = owner

    def request(self, kind, message, *, title='', options=None, preview=None, timeout=60):
        from client.http.client_api import ClientApiClient

        grant = getattr(self.owner, '_interaction_grant', None) or {}
        token = str(grant.get('token') or '').strip()
        if not token:
            raise CommandInteractionError('This Client command has no active interaction grant')
        timeout = max(1, min(int(timeout), 180))
        self.owner._ensure_not_interrupted(fallback_timeout=240)
        result = ClientApiClient().post_data(
            '/api/interactions/client/request', timeout=timeout + 15,
            headers={'X-Script-Grant-Token': token},
            json={'kind': kind, 'title': title, 'message': message,
                  'options': options if options is not None else [],
                  'preview': preview, 'timeout_seconds': timeout},
        )
        self.owner._ensure_not_interrupted(fallback_timeout=240)
        if not isinstance(result, dict):
            raise CommandInteractionError('Invalid interaction reply')
        return result

    def ask(self, message, *, title, secret=False):
        result = self.request('secret' if secret else 'input', message, title=title)
        if result.get('status') != 'answered' or not isinstance(result.get('value'), str):
            raise CommandInteractionError('Input rejected, expired, or cancelled')
        return result['value']

    def select(self, message, labels, *, title):
        result = self.request('select', message, title=title, options=labels)
        if result.get('status') != 'answered' or result.get('value') not in labels:
            raise CommandInteractionError('Selection rejected, expired, or cancelled')
        return result['value']

    def confirm(self, message, *, title='Confirmation'):
        result = self.request('confirm', message, title=title)
        return result.get('status') == 'answered' and result.get('value') is True

    def approve_preview(self, message, preview, *, title='Review execution plan'):
        result = self.request('preview', message, title=title, preview=preview, timeout=120)
        return result.get('status') == 'answered' and result.get('value') is True
