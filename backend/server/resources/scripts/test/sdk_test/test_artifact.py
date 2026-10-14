SCRIPT_METADATA = {
    "display_name": "Artifact Roundtrip Test",
    "description": "",
    "params": [],
    "api_grants": [
        "artifacts:list",
        "artifacts:download"
    ]
}

import os
import tempfile
import time

from client.runtime.sdk import artifact


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    print('=== Script SDK Artifact Roundtrip Test ===')

    stamp = str(int(time.time() * 1000))
    content = f'script-sdk-artifact-roundtrip-{stamp}\n'

    local_dir = tempfile.mkdtemp(prefix='script_sdk_artifact_src_')
    download_dir = tempfile.mkdtemp(prefix='script_sdk_artifact_dst_')
    local_path = os.path.join(local_dir, f'sdk_artifact_{stamp}.txt')

    with open(local_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print('local_path =', local_path)
    print('download_dir =', download_dir)

    saved = artifact.save(
        local_path,
        type='server_files',
        category='script_sdk_test',
        extra={'test': 'artifact_roundtrip', 'stamp': stamp},
    )
    print('saved =', saved)

    artifact_id = saved.get('artifact_id') or saved.get('id') or ''
    original_name = saved.get('original_name') or os.path.basename(local_path)
    ref = artifact_id or original_name
    assert_true(ref, 'artifact.save did not return artifact_id or original_name')

    items = artifact.list(type='server_files')
    print('server_files count =', len(items))
    assert_true(isinstance(items, list), 'artifact.list should return list')

    meta = artifact.get(ref, type='server_files')
    print('resolved meta =', meta)
    assert_true(isinstance(meta, dict), 'artifact.get should return dict')

    downloaded_path = artifact.download(ref, type='server_files', target_path=download_dir)
    print('downloaded_path =', downloaded_path)
    assert_true(os.path.isfile(downloaded_path), 'downloaded file not found')

    with open(downloaded_path, 'r', encoding='utf-8') as f:
        downloaded_content = f.read()

    print('downloaded_content =', downloaded_content.strip())
    assert_true(downloaded_content == content, 'downloaded content mismatch')

    print('PASS')


if __name__ == '__main__':
    main()
