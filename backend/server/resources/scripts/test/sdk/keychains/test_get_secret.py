SCRIPT_METADATA = {'name': 'test/sdk/keychains/test_get_secret',
 'display_name': 'Test Keychains Get Secret',
 'description': 'Create and resolve a synthetic secret without printing its value.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'keychains'],
 'platforms': ['*'],
 'params': [],
 'api_grants': ['keychains:create', 'keychains:resolve']}

import uuid
from client.runtime.sdk import keychains
name = 'rch_sdk_test_' + uuid.uuid4().hex
keychains.create_secret(name, 'test-value')
secret = keychains.get_secret(name)
assert secret.getvalue() == 'test-value'
print('Secret resolved:', name)
print('PASS')
