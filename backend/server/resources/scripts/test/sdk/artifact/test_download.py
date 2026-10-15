SCRIPT_METADATA = {'name': 'test/sdk/artifact/test_download',
 'display_name': 'Test Artifact Download',
 'description': 'Upload a text file, download it and verify the contents.',
 'category': 'Test',
 'tags': ['test', 'sdk', 'artifact'],
 'platforms': ['*'],
 'params': [],
 'api_grants': ['artifacts:list', 'artifacts:download']}

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
    destination = os.path.join(directory, 'downloaded.txt')
    result = artifact.download(artifact_id, type='files', target_path=destination)
    with open(result, encoding='utf-8') as stream:
        assert stream.read() == 'RCH Script SDK artifact test\n'
    print('Downloaded:', os.path.basename(result))
    print('PASS')
