SCRIPT_METADATA = {'name': 'test/sdk/xt/test_run',
 'display_name': 'Test External Tool Run',
 'description': 'Execute an installed tool with the supplied read-only version arguments.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'xt'],
 'platforms': ['*'],
 'params': [{'name': 'exec_name',
             'label': 'Tool executable',
             'type': 'string',
             'description': 'External Tool Manager executable name.',
             'required': False,
             'default': 'ffmpeg'},
            {'name': 'arguments',
             'label': 'Arguments',
             'type': 'string',
             'description': 'Arguments for the selected executable.',
             'required': False,
             'default': '-version'}],
 'api_grants': ['external_tools:catalog']}

from client.runtime.sdk import xt
exec_name = kwargs.get('exec_name') or 'ffmpeg'
if not xt.is_installed(exec_name):
    print('SKIP: install', exec_name, 'in External Tool Manager first.')
else:
    result = xt.run(exec_name, kwargs.get('arguments') or '-version', timeout=15)
    print('Exit code:', result.returncode)
    print('Output:', result.text.strip().splitlines()[0] if result.text.strip() else '(empty)')
    assert result.ok
    print('PASS')
