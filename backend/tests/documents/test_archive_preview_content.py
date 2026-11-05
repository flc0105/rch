"""Content-based preview and shared ZIP entry bounds."""

from io import BytesIO
from types import SimpleNamespace
import zipfile

import pytest

from core.utils.zip_peek import ZipPeekService
from server.application.artifact.artifact_preview_service import ArtifactPreviewService


def _service(path, name):
    artifact = {'saved_path': str(path), 'original_name': name, 'artifact_id': 'A', 'raw_url': '/raw/A'}
    registry = SimpleNamespace(get_artifact_by_id=lambda _id: artifact)
    service = SimpleNamespace(registry_service=registry, MAX_PREVIEW_TEXT_BYTES=4096,
                              get_artifact_file_path=lambda _id: str(path))
    return ArtifactPreviewService(service)


@pytest.mark.parametrize('name,contents,kind', [
    ('README', b'hello\nUTF-8!', 'text'),
    ('unusual.dat', 'no extension dependency'.encode(), 'text'),
    ('utf16.data', b'\xff\xfe' + '你好'.encode('utf-16-le'), 'text'),
    ('lying.txt', b'\x00\x01\x03hello', 'unsupported'),
    ('image.txt', b'\x89PNG\r\n\x1a\npretend image bytes', 'image'),
    ('not-an-image.jpg', b'content is plain text', 'text'),
])
def test_preview_content_precedes_extension(tmp_path, name, contents, kind):
    target = tmp_path / name
    target.write_bytes(contents)
    payload = _service(target, name).build_preview_payload('A')
    assert payload['type'] == kind
    if kind == 'text':
        assert payload['editable'] is True
        assert payload['truncated'] is False


def test_zip_preview_shared_api_and_bounded_entries(tmp_path):
    target = tmp_path / 'arbitrary_extension.blob'
    with zipfile.ZipFile(target, 'w') as zf:
        zf.writestr('nested/info', 'Hello zip 世界')
        zf.writestr('nested/binary.dat', b'\x00\x01\x02')
        zf.writestr('nested/big.log', b'x' * 40)
    preview = _service(target, target.name)
    assert preview.build_preview_payload('A')['type'] == 'archive'
    inspection = preview.inspect_zip_artifact('A')
    assert inspection['file_count'] == 3
    assert inspection['entry_count'] == 3
    assert inspection['tree'][0]['is_dir']
    assert preview.read_zip_artifact_entry('A', 'nested/info')['content'] == 'Hello zip 世界'
    assert preview.read_zip_artifact_entry('A', 'nested/binary.dat')['type'] == 'binary'
    limited = ZipPeekService()
    limited.PEEK_MAX_ENTRY_BYTES = 16
    with pytest.raises(ValueError, match='too large'):
        limited.read_zip_text_entry(target, 'nested/big.log')
    with pytest.raises(FileNotFoundError):
        limited.read_zip_text_entry(target, 'missing.txt')


def test_zip_preview_refuses_oversized_archive_and_unsafe_entry(tmp_path):
    target = tmp_path / 'malicious.zip'
    with zipfile.ZipFile(target, 'w') as zf:
        zf.writestr('../escape.txt', 'Bad relative path')
    peek = ZipPeekService()
    with pytest.raises(ValueError, match='traversal'):
        peek.inspect_zip(target)
    peek.PEEK_MAX_ARCHIVE_BYTES = 3
    with pytest.raises(ValueError, match='too large'):
        peek.inspect_zip(target)
