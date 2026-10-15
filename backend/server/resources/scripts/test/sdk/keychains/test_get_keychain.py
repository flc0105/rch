SCRIPT_METADATA = {'name': 'test/sdk/keychains/test_get_keychain',
 'display_name': 'Test Keychains Generic Lookup',
 'description': 'Resolve a synthetic credential through get_keychain.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'keychains'],
 'platforms': ['*'],
 'params': [],
 'api_grants': ['keychains:create', 'keychains:resolve']}

import uuid
from client.runtime.sdk import keychains
name = 'rch_sdk_test_' + uuid.uuid4().hex
keychains.create_secret(name, 'test-value')
result = keychains.get_keychain(name, kind='secret')
assert result.name == name and result.value.getvalue() == 'test-value'
print('Credential resolved:', result.name)
print('PASS')
