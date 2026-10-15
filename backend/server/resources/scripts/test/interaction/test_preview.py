SCRIPT_METADATA = {'name': 'test/interaction/test_preview',
 'display_name': 'Test Structured Preview',
 'description': 'Show a summary and table, then report the approval decision.',
 'category': 'Test',
 'tags': ['test', 'interaction'],
 'platforms': ['*'],
 'params': [],
 'api_grants': ['interactions:request']}

from client.runtime.sdk import context
preview = {
    'summary': [{'label': 'Action', 'value': 'Harmless SDK test'}],
    'columns': [{'key': 'item', 'label': 'Item'}, {'key': 'value', 'label': 'Value'}],
    'rows': [{'item': 'Result', 'value': 'No system changes'}],
    'notice': 'This preview does not modify files or processes.',
}
approved = context.approve_preview('Review the test preview:', preview, title='Preview Test')
print('APPROVED' if approved else 'REJECTED')
