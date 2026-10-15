SCRIPT_METADATA = {'name': 'test/sdk/xt/test_tool',
 'display_name': 'Test External Tool Handle',
 'description': 'Create an External Tool SDK handle.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'xt'],
 'platforms': ['*'],
 'params': [{'name': 'exec_name',
             'label': 'Tool executable',
             'type': 'string',
             'description': 'External Tool Manager executable name.',
             'required': False,
             'default': 'ffmpeg'}],
 'api_grants': []}

from client.runtime.sdk import xt
exec_name = kwargs.get('exec_name') or 'ffmpeg'
handle = xt.tool(exec_name)
assert handle.exec_name == exec_name
print('Handle:', handle.exec_name)
print('PASS')
