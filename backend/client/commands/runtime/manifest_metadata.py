"""Declarative execution metadata shared by ordinary Client commands and ACMD."""


def command_metadata(handler, *, kind='command'):
    output = getattr(handler, 'command_output', 'collect')
    return {
        'kind': kind,
        'source': 'client',
        'cancel_policy': getattr(handler, 'command_cancel_mode', 'none'),
        'timeout': getattr(handler, 'command_timeout', None),
        'interaction': {
            'may_request': bool(getattr(handler, 'command_interaction', False)
                                or getattr(handler, 'requires_confirmation', False)),
        },
        'output': output,
        **({'confirmation': True} if getattr(handler, 'requires_confirmation', False) else {}),
    }
