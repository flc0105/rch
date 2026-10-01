def normalize_mac_address(value) -> str:
    text = str(value or '').strip().lower().replace('-', ':')
    if not text:
        return ''

    if ':' in text:
        parts = [part.zfill(2) for part in text.split(':') if part]
    else:
        compact = ''.join(ch for ch in text if ch in '0123456789abcdef')
        if len(compact) != 12:
            return ''
        parts = [compact[index:index + 2] for index in range(0, 12, 2)]

    if len(parts) != 6:
        return ''

    for part in parts:
        if len(part) != 2 or any(ch not in '0123456789abcdef' for ch in part):
            return ''

    if parts == ['00', '00', '00', '00', '00', '00']:
        return ''

    return ':'.join(parts)
