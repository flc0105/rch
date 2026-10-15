SCRIPT_METADATA = {'name': 'test/sdk/keychains/test_get_login',
 'display_name': 'Test Keychains Get Login',
 'description': 'Create and resolve a synthetic login without printing its password.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'keychains'],
 'platforms': ['*'],
 'params': [],
 'api_grants': ['keychains:create', 'keychains:resolve']}

import uuid
from client.runtime.sdk import keychains
name = 'rch_sdk_test_' + uuid.uuid4().hex
keychains.create_login(name, 'sdk-user', 'test-password')
login = keychains.get_login(name)
assert login.username == 'sdk-user'
assert login.password.getvalue() == 'test-password'
print('Login resolved:', login.username)
print('PASS')
