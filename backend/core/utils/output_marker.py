OUTPUT_MARKERS = {
    'info': '[*]',
    'success': '[+]',
    'warning': '[!]',
    'error': '[-]',
}


def mark_output(text, level='info'):
    value = '' if text is None else str(text)
    normalized_level = str(level or 'info').strip().lower()
    marker = OUTPUT_MARKERS.get(normalized_level, OUTPUT_MARKERS['info'])
    stripped = value.lstrip()

    if (
        stripped.startswith('[*]') or
        stripped.startswith('[+]') or
        stripped.startswith('[!]') or
        stripped.startswith('[-]')
    ):
        return value

    return f'{marker} {value}'


def info(text):
    return mark_output(text, 'info')


def success(text):
    return mark_output(text, 'success')


def warning(text):
    return mark_output(text, 'warning')


def error(text):
    return mark_output(text, 'error')

def render_result_message(event: dict) -> str:
    """Project one Result event into visible text, without changing its facts.

    Only an explicitly levelled progress message receives an Output Marker.
    Ordinary progress and all stdout / structured chunks remain untouched.
    """
    message = str(event.get('message') or event.get('text') or '')
    if event.get('event_type') == 'progress' and event.get('level') and message:
        return mark_output(message, event['level'])
    return message
