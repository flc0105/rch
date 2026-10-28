"""Declarative execution metadata shared by ordinary Client commands and ACMD."""


def command_metadata(handler, *, kind='command'):
    grants = (
        *getattr(handler, 'api_grants', ()),
        *getattr(handler, 'argument_command_grants', ()),
    )
    output = getattr(handler, 'command_output', 'collect')
    return {
        'kind': kind,
        'source': 'client',
        'cancel_policy': (getattr(handler, 'manifest_cancel_policy', None)
                          or getattr(handler, 'command_cancel_mode', 'none')),
        'timeout': getattr(handler, 'command_timeout', None),
        'confirmation': {
            'required': bool(getattr(handler, 'requires_confirmation', False)),
            'allow_no_confirm': bool(getattr(handler, 'allow_no_confirm', False)),
        },
        'interaction': {
            'may_request': bool(getattr(handler, 'command_interaction', False)
                                or getattr(handler, 'requires_confirmation', False)
                                or 'interactions:request' in grants),
        },
        'output': output,
        'streaming': output == 'stream',
    }
