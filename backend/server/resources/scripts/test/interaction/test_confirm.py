SCRIPT_METADATA = {'name': 'test/interaction/test_confirm',
 'display_name': 'Test Confirmation',
 'description': 'Request explicit approval and report the decision.',
 'category': 'Test',
 'tags': ['test', 'interaction'],
 'platforms': ['*'],
 'params': [],
 'api_grants': ['interactions:request']}

from client.runtime.sdk import context
approved = context.confirm('Approve this harmless test?', title='Confirm Test')
print('APPROVED' if approved else 'REJECTED')
