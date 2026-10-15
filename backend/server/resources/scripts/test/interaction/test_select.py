SCRIPT_METADATA = {'name': 'test/interaction/test_select',
 'display_name': 'Test Selection',
 'description': 'Show a fixed choice and print the selected value.',
 'category': 'Test',
 'tags': ['test', 'interaction'],
 'platforms': ['*'],
 'params': [],
 'api_grants': ['interactions:request']}

from client.runtime.sdk import context
choice = context.select('Choose a value:', ['Alpha', 'Beta'], title='Select Test')
assert choice in ('Alpha', 'Beta')
print('Selected:', choice)
print('PASS')
