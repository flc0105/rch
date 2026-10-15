SCRIPT_METADATA = {'name': 'test/sdk/command/test_run_shell',
 'display_name': 'Test Command Run Shell',
 'description': 'Run a harmless shell command and inspect its exit code.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'command'],
 'platforms': ['*'],
 'params': [],
 'api_grants': []}

from client.runtime.sdk import command
result = command.run_shell('echo rch-sdk-shell')
assert result.ok and 'rch-sdk-shell' in result.stdout, result.stderr
print(result.stdout.strip())
print('PASS')
