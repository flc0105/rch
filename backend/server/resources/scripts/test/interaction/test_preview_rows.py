SCRIPT_METADATA = {
    'name': 'test/interaction/test_preview_rows',
    'display_name': 'Test Preview Row Selection',
    'description': 'Verify selectable preview rows without changing any files.',
    'category': 'Test',
    'tags': ['test', 'interaction'],
    'platforms': ['*'],
    'params': [
        {'name': 'directory_pattern', 'label': 'Directory pattern (read only)',
         'type': 'string', 'required': False, 'default': '',
         'description': 'Optional path containing one directory-level *.'},
    ],
    'api_grants': ['interactions:request'],
}

from client.runtime.sdk import context
from client.runtime.sdk.path_patterns import expand_directory_pattern

pattern = str(kwargs.get('directory_pattern') or '').strip()
if pattern:
    matches = expand_directory_pattern(pattern)
    print(f'PATH MATCHES: {len(matches)}')
else:
    print('PATH MATCHES: not requested')

preview = {
    'columns': [{'key': 'item', 'label': 'Item'}, {'key': 'size', 'label': 'Size'}],
    'rows': [{'item': 'First example', 'size': '1 MiB'},
             {'item': 'Second example', 'size': '2 MiB'},
             {'item': 'Third example', 'size': '3 MiB'}],
    'row_ids': ['first', 'second', 'third'],
}
try:
    selected = context.select_preview_rows('Choose example items:', preview,
                                           title='Row Selection Test')
except Exception as exc:
    print(f'CANCELLED: {exc}')
else:
    print(f'SELECTED: {", ".join(selected) if selected else "none"}')
    print('PASS: no changes performed')
