SCRIPT_METADATA = {
    'name': 'common/test/interaction_advanced_example',
    'display_name': 'Advanced Interactions Demo',
    'description': 'Demonstrate option select, secret input, and optional approval; no side effects.',
    'platforms': ['common'], 'category': 'Test', 'params': [],
    'api_grants': ['interactions:request'],
}

mode = context.select('Choose a demo action:', ['Preview', 'Execute'], title='Select demo mode')
if mode == 'Preview':
    print('Preview only. Nothing executed.')
else:
    secret = context.ask('Enter a sample secret (not printed):', title='Secret input', secret=True)
    if context.confirm('Execute harmless demo?', title='Approval'):
        print('Executed harmless demo. Secret was not disclosed.')
    else:
        print('Rejected. Nothing executed.')
