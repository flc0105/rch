SCRIPT_METADATA = {'name': 'test/sdk/artifact/test_get',
 'display_name': 'Test Artifact Get Metadata',
 'description': 'Upload a small file and retrieve its Artifact metadata.',
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
    metadata = artifact.get(artifact_id, type='files')
    assert isinstance(metadata, dict) and metadata.get('artifact_id') == artifact_id
    print('File:', metadata.get('original_name') or metadata.get('stored_name'))
    print('PASS')
