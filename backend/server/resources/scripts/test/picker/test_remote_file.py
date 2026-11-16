SCRIPT_METADATA = {'name': 'test/picker/test_remote_file',
 'display_name': 'Test Remote File Picker',
 'description': 'Choose one remote path and verify the returned value.',
 'category': 'Test',
 'tags': ['test', 'picker'],
 'platforms': ['*'],
 'params': [{'name': 'selected_file',
             'label': 'Remote path',
             'type': 'remote_file',
             'description': 'Select a path.',
             'required': True},{'name': 'selected_files',
             'label': 'Remote paths',
             'type': 'remote_files',
             'description': 'Select one or more paths.',
             'required': True,
             'multiple': True},{'name': 'selected_folder',
             'label': 'Remote path',
             'type': 'remote_folder',
             'description': 'Select a path.',
             'required': True},{'name': 'selected_folders',
             'label': 'Remote paths',
             'type': 'remote_folders',
             'description': 'Select one or more paths.',
             'required': True,
             'multiple': True}],
 }

selected_file = kwargs['selected_file']
assert isinstance(selected_file, str) and selected_file.strip()
print(selected_file)


paths = kwargs['selected_files']
assert isinstance(selected_files, list), 'Expected a list of remote paths.'
assert selected_files and all(isinstance(item, str) and item.strip() for item in selected_files)
for path in selected_files:
    print(path)


selected_folder = kwargs['selected_folder']
assert isinstance(selected_folder, str) and selected_folder.strip()
print(selected_folder)

selected_folders = kwargs['selected_folders']
assert isinstance(selected_folders, list), 'Expected a list of remote paths.'
assert selected_folders and all(isinstance(item, str) and item.strip() for item in selected_folders)
for path in selected_folders:
    print(path)

print('PASS')

