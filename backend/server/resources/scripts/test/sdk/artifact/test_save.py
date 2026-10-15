SCRIPT_METADATA = {'name': 'test/sdk/artifact/test_save',
 'display_name': 'Test Artifact Save',
 'description': 'Upload a generated small text file to the Artifact Center.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'artifact'],
 'platforms': ['*'],
 'params': [],
 'api_grants': []}

import os
import tempfile
from client.runtime.sdk import artifact
with tempfile.TemporaryDirectory(prefix='rch_sdk_artifact_') as directory:
    path = os.path.join(directory, 'sdk_save_test.txt')
    with open(path, 'w', encoding='utf-8') as stream:
        stream.write('RCH SDK upload test\n')
    item = artifact.save(path, type='files', category='sdk_test')
    assert item.get('artifact_id') or item.get('id'), item
    print('Saved:', item.get('artifact_id') or item.get('id'))
print('PASS')
