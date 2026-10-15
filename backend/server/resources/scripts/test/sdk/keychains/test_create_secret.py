SCRIPT_METADATA = {'name': 'test/sdk/keychains/test_create_secret',
 'display_name': 'Test Keychains Create Secret',
 'description': 'Create a synthetic secret for SDK testing.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'keychains'],
 'platforms': ['*'],
 'params': [],
 'api_grants': ['keychains:create']}

import uuid
from client.runtime.sdk import keychains
name = 'rch_sdk_test_' + uuid.uuid4().hex
created = keychains.create_secret(name, 'test-value', note='SDK test credential')
assert created.name == name and created.value.getvalue() == 'test-value'
print('Created:', created.name)
print('PASS')
