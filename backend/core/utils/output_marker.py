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