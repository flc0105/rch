SCRIPT_METADATA = {'name': 'test/sdk/context/test_context',
 'display_name': 'Test Context SDK',
 'description': 'Check the current Script context, environment, grant, and progress output.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'context'],
 'platforms': ['*'],
 'params': [],
 'api_grants': ['workspace:read']}

from client.runtime.sdk import context

fields = {
    'client_id': context.client_id,
    'command_id': context.command_id,
    'hostname': context.hostname,
    'machine_id': context.machine_id,
    'script_name': context.script_name,
    'os_type': context.os_type,
    'os_alias': context.os_alias,
    'os_ver': context.os_ver,
    'arch': context.arch,
}
for name, read in fields.items():
    value = read()
    assert value is None or isinstance(value, (str, int)), name
    print(f'{name}: {value}')

paths = context.system_paths()
assert isinstance(paths, dict)
print('System paths:', ', '.join(sorted(paths)) or '(none)')

script_context = context.get_script_context()
assert isinstance(script_context, dict)
print('Context keys:', ', '.join(sorted(script_context)) or '(none)')

grant = context.get_script_grant()
token = context.get_script_grant_token()
assert isinstance(grant, dict)
assert isinstance(token, str) and token, 'Script grant token is missing.'
print('Grant scopes:', grant.get('scopes') or grant.get('api_grants') or [])
print('Grant token present:', bool(token))

context.progress('SDK context progress test')
print('PASS')
