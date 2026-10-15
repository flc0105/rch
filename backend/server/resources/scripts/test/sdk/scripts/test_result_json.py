SCRIPT_METADATA = {'name': 'test/sdk/scripts/test_result_json',
 'display_name': 'Test Script Result JSON',
 'description': 'Parse JSON output using the SDK ScriptResult object.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'scripts'],
 'platforms': ['*'],
 'params': [],
 'api_grants': []}

from client.runtime.sdk.scripts import ScriptResult
result = ScriptResult(name='local', returncode=0, stdout="{\"ok\": true}")
assert result.ok and result.json() == {"ok": True}
print("JSON parsed:", result.json())
print("PASS")
