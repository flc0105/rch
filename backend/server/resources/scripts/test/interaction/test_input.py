SCRIPT_METADATA = {'name': 'test/interaction/test_input',
 'display_name': 'Test Text Input',
 'description': 'Request ordinary text input and display the answer.',
 'category': 'Test',
 'tags': ['test', 'interaction'],
 'platforms': ['*'],
 'params': [],
 'api_grants': ['interactions:request']}

from client.runtime.sdk import context
value = context.ask('Enter a short test label:', title='Input Test', placeholder='Sample')
print('Value:', value)
print('PASS')
