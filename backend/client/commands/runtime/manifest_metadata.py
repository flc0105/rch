"""Declarative Client command catalog metadata (runtime policies stay with handlers)."""


def command_metadata(handler, *, kind='command', platform=None):
    return {
        'kind': kind,
        'source': 'client',
        'cancel_policy': getattr(handler, 'command_cancel_mode', 'none'),
        'may_interact': bool(getattr(handler, 'command_may_interact', False)
                             or getattr(handler, 'requires_confirmation', False)),
        **({'completion': getattr(handler, 'command_completion').to_dict()}
           if getattr(handler, 'command_completion', None) is not None else {}),
        **({'confirmation': True} if getattr(handler, 'requires_confirmation', False) else {}),
    }
