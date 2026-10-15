SCRIPT_METADATA = {'name': 'test/sdk/command/test_stream_shell',
 'display_name': 'Test Command Stream Shell',
 'description': 'Run a short shell command with streamed output.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'command'],
 'platforms': ['*'],
 'params': [],
 'api_grants': []}

from client.runtime.sdk import command
result = command.stream_shell('ping -c 4 127.0.0.1', timeout=10)
assert result.ok, result.returncode
print('Exit code:', result.returncode)
print('PASS')
