SCRIPT_METADATA = {'name': 'test/sdk/keychains/test_list',
 'display_name': 'Test Keychains List',
 'description': 'List Keychain metadata without revealing secret values.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'keychains'],
 'platforms': ['*'],
 'params': [],
 }

from client.runtime.sdk import keychains
items = keychains.list()
assert isinstance(items, list)
print('Machine credentials:', len(items))
print('PASS')
