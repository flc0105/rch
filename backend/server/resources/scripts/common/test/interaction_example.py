SCRIPT_METADATA = {
    'name': 'common/test/interaction_example',
    'display_name': 'Interactive Script Demo',
    'description': 'Test an explicit approval and text input; performs no file changes.',
    'platforms': ['common'],
    'category': 'Test',
    'params': [],
    'api_grants': ['interactions:request'],
}

print('[Interaction Demo] Preview: harmless output only. No files will be modified.', flush=True)
if context.confirm('Continue with the harmless demonstration?', title='Approve Script Demo'):
    try:
        value = context.ask('Enter a label for the execution result:', placeholder='Demo label')
    except Exception as exc:
        print(f'[Interaction Demo] Input aborted: {exc}')
    else:
        print(f'[Interaction Demo] Approved and executed. Label: {value}')
else:
    print('[Interaction Demo] Not executed (rejected or timed out).')
