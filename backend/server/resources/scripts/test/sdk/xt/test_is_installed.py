SCRIPT_METADATA = {'name': 'test/sdk/xt/test_is_installed',
 'display_name': 'Test External Tool Is Installed',
 'description': 'Check whether a configured External Tool is installed.',
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
installed = xt.is_installed(exec_name)
assert isinstance(installed, bool)
print('Installed:', installed)
print('PASS')
