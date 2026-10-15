SCRIPT_METADATA = {'name': 'test/sdk/scripts/test_run',
 'display_name': 'Test Script Run',
 'description': 'Run the installed Context Identity test as a child Script.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'scripts'],
 'platforms': ['*'],
 'params': [],
 'api_grants': ['scripts:read']}

from client.runtime.sdk import scripts
result = scripts.run('test/sdk/context/test_context')
assert result.ok, result.stderr
assert 'PASS' in result.stdout
print('Child result:', result.returncode)
print('PASS')
