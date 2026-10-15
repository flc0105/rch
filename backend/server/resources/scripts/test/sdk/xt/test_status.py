SCRIPT_METADATA = {'name': 'test/sdk/xt/test_status',
 'display_name': 'Test External Tool Status',
 'description': 'Check the installation status of a configured External Tool.',
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
status = xt.tool(exec_name).status()
assert isinstance(status, dict)
print('Installed:', bool(status.get('installed')))
print('PASS')
