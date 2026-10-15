SCRIPT_METADATA = {'name': 'test/sdk/command/test_dynamic_client',
 'display_name': 'Test Command Dynamic Client',
 'description': 'Invoke the exported Client command using the dynamic SDK method.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'command'],
 'platforms': ['*'],
 'params': [],
 'api_grants': []}

from client.runtime.sdk import command
result = command.pwd()
assert result.ok, result.output
print('Working directory:', result.output)
print('PASS')
