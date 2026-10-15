SCRIPT_METADATA = {'name': 'test/interaction/test_secret',
 'display_name': 'Test Secret Input',
 'description': 'Request protected input without showing its contents.',
 'category': 'Test',
 'tags': ['test', 'interaction'],
 'platforms': ['*'],
 'params': [],
 'api_grants': ['interactions:request']}

from client.runtime.sdk import context
value = context.ask('Enter any test text:', title='Secret Test', secret=True)
print('Received:', bool(value))
print('PASS')
