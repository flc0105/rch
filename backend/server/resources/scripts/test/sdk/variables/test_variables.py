SCRIPT_METADATA = {
    'name': 'test/sdk/variables/test_variables',
    'display_name': 'Test Client Variables SDK',
    'description': 'Read Client runtime variables and expand a command template.',
    'category': 'Test',
    'tags': ['test', 'sdk', 'variables'],
    'platforms': ['*'],
    'params': [],
    'api_grants': [],
}

from client.runtime.sdk import variables

for name in ('launch_command', 'runtime', 'exec_path', 'pid', 'client_id'):
    value = variables.get(f'rch:{name}')
    assert value, f'rch:{name} is empty'
    print(f'{name}: {value}')

expanded = variables.expand('Client ${rch:client_id} in ${rch:runtime}')
assert '${rch:' not in expanded
print('expanded:', expanded)
print('PASS')
