SCRIPT_METADATA = {'name': 'test/sdk/artifact/test_list',
 'display_name': 'Test Artifact List',
 'description': 'List the Artifact Center items without downloading content.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'artifact'],
 'platforms': ['*'],
 'params': [],
 'api_grants': ['artifacts:list']}

from client.runtime.sdk import artifact
items = artifact.list(type='files')
assert isinstance(items, list)
print('File artifacts:', len(items))
print('PASS')
