SCRIPT_METADATA = {'name': 'test/sdk/keychains/test_create_login',
 'display_name': 'Test Keychains Create Login',
 'description': 'Create a synthetic login for SDK testing.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'keychains'],
 'platforms': ['*'],
 'params': [],
 'api_grants': ['keychains:create']}

import uuid
from client.runtime.sdk import keychains
name = 'rch_sdk_test_' + uuid.uuid4().hex
created = keychains.create_login(name, 'sdk-user', 'test-password', note='SDK test credential')
assert created.name == name and created.username == 'sdk-user'
print('Created:', created.name)
print('PASS')
