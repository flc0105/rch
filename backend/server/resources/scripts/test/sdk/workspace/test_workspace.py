SCRIPT_METADATA = {'name': 'test/sdk/workspace/test_workspace',
 'display_name': 'Test Workspace SDK',
 'description': 'Show workspace shortcuts and check pinned-path lookup.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'workspace'],
 'platforms': ['*'],
 'params': [],
 'api_grants': ['workspace:read']}

from client.runtime.sdk import workspace

paths = workspace.system_paths()
assert isinstance(paths, dict)
print('System paths:', ', '.join(sorted(paths)) or '(none)')

for name in ('root', 'home', 'desktop', 'documents', 'downloads',
             'temp', 'executable', 'icloud'):
    value = getattr(workspace, name)()
    assert isinstance(value, str), name
    print(f'{name}: {value or "(not available)"}')

items = workspace.list()
pinned = workspace.as_dict()
assert isinstance(items, list) and isinstance(pinned, dict)
print('Pinned paths:', len(items))

if pinned:
    name, expected = next(iter(pinned.items()))
    assert workspace.get(name) == expected
    assert workspace.path(name) == expected
    print(f'Pinned lookup: {name} -> {expected}')
else:
    assert workspace.get('rch_sdk_missing_path', default='not-found') == 'not-found'
    assert workspace.path('rch_sdk_missing_path', default='not-found') == 'not-found'
    print('Pinned lookup: no saved paths')

print('PASS')
