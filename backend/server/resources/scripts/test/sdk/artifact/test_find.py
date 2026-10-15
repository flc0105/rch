SCRIPT_METADATA = {'name': 'test/sdk/artifact/test_find',
 'display_name': 'Test Artifact Find by Name',
 'description': 'Upload a unique file and locate it by exact filename.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'artifact'],
 'platforms': ['*'],
 'params': [],
 'api_grants': ['artifacts:list']}

import os
import tempfile
import uuid
from client.runtime.sdk import artifact

name = f'rch_sdk_test_{uuid.uuid4().hex}.txt'
with tempfile.TemporaryDirectory(prefix='rch_sdk_artifact_') as directory:
    source = os.path.join(directory, name)
    with open(source, 'w', encoding='utf-8') as stream:
        stream.write('RCH Script SDK artifact test\n')
    item = artifact.save(source, type='files', category='sdk_test')
    artifact_id = item.get('artifact_id') or item.get('id')
    assert artifact_id, 'No artifact ID was returned.'
    matches = artifact.find_by_file_name(name, type='files')
    assert any(row.get('artifact_id') == artifact_id for row in matches), matches
    print('Found:', len(matches))
    print('PASS')
