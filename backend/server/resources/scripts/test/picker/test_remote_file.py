SCRIPT_METADATA = {'name': 'test/picker/test_remote_file',
 'display_name': 'Test Remote File Picker',
 'description': 'Choose one remote path and verify the returned value.',
 'category': 'Test',
 'tags': ['test', 'picker'],
 'platforms': ['*'],
 'params': [{'name': 'selected_path',
             'label': 'Remote path',
             'type': 'remote_file',
             'description': 'Select a path.',
             'required': True}],
 'api_grants': []}

path = kwargs['selected_path']
assert isinstance(path, str) and path.strip()
print(path)
print('PASS')
