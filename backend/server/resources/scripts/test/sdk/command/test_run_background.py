SCRIPT_METADATA = {'name': 'test/sdk/command/test_run_background',
 'display_name': 'Test Command Run Background',
 'description': 'Launch a short background shell command and display its PID.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'command'],
 'platforms': ['*'],
 'params': [],
 'api_grants': []}

from client.runtime.sdk import command
process = command.run_background('echo rch-sdk-background')
assert process.pid > 0
print('Started PID:', process.pid)
print('PASS')
