"""Render the original grouped Client command help from trusted command metadata."""

HELP_GROUP_TITLES = {
    'shell': 'Shell / Execution',
    'file': 'File',
    'file_path': 'File Path / Web',
    'job': 'Job',
    'session': 'Session',
    'platform': 'Platform',
    'acmd': 'Acmd',
    'general': 'General',
}
HELP_GROUP_ORDER = ('shell', 'file', 'file_path', 'job', 'session',
                    'platform', 'acmd', 'general')


def render_grouped_client_help(grouped):
    lines = []
    names = [*HELP_GROUP_ORDER, *(name for name in grouped if name not in HELP_GROUP_ORDER)]
    for group_name in names:
        items = grouped.get(group_name) or []
        if not items:
            continue
        lines.append(f'[{HELP_GROUP_TITLES.get(group_name, group_name)}]')
        for name, description in sorted(items, key=lambda item: item[0].lower()):
            lines.append(f'{name:<24}{description}')
        lines.append('')
    return '\n'.join(lines).rstrip()
