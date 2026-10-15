SCRIPT_METADATA = {'name': 'test/sdk/xt/test_which',
 'display_name': 'Test External Tool Which',
 'description': 'Resolve an installed External Tool executable path.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'xt'],
 'platforms': ['*'],
 'params': [{'name': 'exec_name',
             'label': 'Tool executable',
             'type': 'string',
             'description': 'External Tool Manager executable name.',
             'required': False,
             'default': 'ffmpeg'}],
 'api_grants': ['external_tools:catalog']}

from client.runtime.sdk import xt
exec_name = kwargs.get('exec_name') or 'ffmpeg'
if not xt.is_installed(exec_name):
    print('SKIP: install', exec_name, 'in External Tool Manager first.')
else:
    path = xt.which(exec_name)
    assert path
    print('Executable:', path)
    print('PASS')
