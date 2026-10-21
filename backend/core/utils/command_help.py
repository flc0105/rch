"""Render Client help grouped and sorted by its displayed group titles."""

HELP_GROUP_TITLES = {
    'shell': 'Shell',
    'file': 'File',
    'file_path': 'File Path / Web',
    'job': 'Job',
    'session': 'Session',
    'platform': 'Platform',
    'acmd': 'Acmd',
    'general': 'General',
}


def render_grouped_client_help(grouped):
    lines = []
    names = sorted(grouped, key=lambda name: (HELP_GROUP_TITLES.get(name, name).casefold(), name.casefold()))
    for group_name in names:
        items = grouped.get(group_name) or []
        if not items:
            continue
        lines.append(f'[{HELP_GROUP_TITLES.get(group_name, group_name)}]')
        for name, description in sorted(items, key=lambda item: item[0].lower()):
            lines.append(f'{name:<24}{description}')
        lines.append('')
    return '\n'.join(lines).rstrip()
