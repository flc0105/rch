SCRIPT_METADATA = {'name': 'test/picker/test_remote_files',
 'display_name': 'Test Remote Files Picker',
 'description': 'Choose one or more remote paths and verify the returned value.',
 'category': 'Test',
 'tags': ['test', 'picker'],
 'platforms': ['*'],
 'params': [{'name': 'selected_paths',
             'label': 'Remote paths',
             'type': 'remote_files',
             'description': 'Select one or more paths.',
             'required': True,
             'multiple': True}],
 'api_grants': []}

paths = kwargs['selected_paths']
assert isinstance(paths, list), 'Expected a list of remote paths.'
assert paths and all(isinstance(item, str) and item.strip() for item in paths)
for path in paths:
    print(path)
print('PASS')
