SCRIPT_METADATA = {'name': 'test/sdk/command/test_run_client',
 'display_name': 'Test Command Run Client',
 'description': 'Invoke the exported Client pwd command.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'command'],
 'platforms': ['*'],
 'params': [],
 'api_grants': []}

from client.runtime.sdk import command
result = command.run_client('pwd')
assert result.ok, result.output
print('Working directory:', result.output)
print('PASS')
