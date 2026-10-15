SCRIPT_METADATA = {'name': 'test/sdk/events/test_emit',
 'display_name': 'Test Device Event Emit',
 'description': 'Emit a harmless SDK test event to the current Server.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'events'],
 'platforms': ['*'],
 'params': [],
 'api_grants': []}

from client.runtime.sdk import events
result = events.emit('sdk.test', data={'status': 'ok'}, message='Script SDK event test')
assert isinstance(result, dict)
print('Event accepted:', result.get('event_id') or result.get('id') or 'yes')
print('PASS')
