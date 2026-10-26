"""Focused behavior tests for project module: documents."""

import hashlib
import os
from pathlib import Path
import pytest
from server.application.documents.document_library_service import DocumentLibraryService
import tempfile
import unittest
from types import SimpleNamespace
from core.utils.text_encoding import decode_text_bytes, preview_text_bytes, encode_for_existing_file
from server.application.artifact.artifact_preview_service import ArtifactPreviewService
from server.application.web.artifact_api import WebArtifactApi
from client.commands.common.services.filesystem.file_system_service import FileSystemService


@pytest.fixture
def library(tmp_path):
    root = tmp_path / 'docs'
    root.mkdir()
    return DocumentLibraryService({'notes': {'label': 'Notes', 'path': str(root)}}, 512 * 1024)


def test_create_tree_read_update(library, tmp_path):
    assert library.list_roots() == {'items': [{'id': 'notes', 'label': 'Notes'}]}
    library.create_directory('notes', 'nested')
    created = library.create_document('notes', 'nested/demo.md')
    assert created['content'] == ''
    assert library.list_tree('notes')['items'][0]['type'] == 'directory'
    assert library.list_tree('notes', 'nested')['items'][0]['path'] == 'nested/demo.md'
    result = library.save_document('notes', 'nested/demo.md', '# 你好\n', 'utf-8', created['sha256'])
    assert library.read_document('notes', 'nested/demo.md')['content'] == '# 你好\n'
    assert (tmp_path / 'docs/nested/demo.md').read_bytes() == '# 你好\n'.encode()
    assert result['sha256'] == hashlib.sha256('# 你好\n'.encode()).hexdigest()
    with pytest.raises(FileExistsError):
        library.create_document('notes', 'nested/demo.md')


def test_conflict_preserves_external_changes(library, tmp_path):
    doc = library.create_document('notes', 'a.md')
    path = tmp_path / 'docs/a.md'
    path.write_bytes(b'external editor')
    with pytest.raises(ValueError, match='changed on disk'):
        library.save_document('notes', 'a.md', 'overwritten', 'utf-8', doc['sha256'])
    assert path.read_bytes() == b'external editor'


@pytest.mark.parametrize('path', ['/etc/passwd.md', '../outside.md', 'a/../b.md', 'a//b.md', 'a\\b.md', 'not-markdown.txt', '.hidden.md', '.git/file.md'])
def test_unsafe_paths_rejected(library, path):
    with pytest.raises(ValueError):
        library.create_document('notes', path)


def test_symlinks_rejected(library, tmp_path):
    outside = tmp_path / 'external'
    outside.mkdir()
    (outside / 'secret.md').write_text('secret')
    (tmp_path / 'docs/alias').symlink_to(outside, target_is_directory=True)
    assert library.list_tree('notes')['items'] == []
    with pytest.raises(ValueError, match='Symbolic links'):
        library.read_document('notes', 'alias/secret.md')
    (tmp_path / 'docs/leaf.md').symlink_to(outside / 'secret.md')
    with pytest.raises(ValueError, match='Symbolic links'):
        library.read_document('notes', 'leaf.md')


@pytest.mark.parametrize('raw,codec', [
    (b'\xef\xbb\xbf# hi', 'utf-8-sig'),
    (b'\xff\xfe' + '# hi'.encode('utf-16-le'), 'utf-16-le'),
    (b'\xfe\xff' + '# hi'.encode('utf-16-be'), 'utf-16-be'),
])
def test_bom_roundtrip(library, tmp_path, raw, codec):
    path = tmp_path / 'docs/a.md'
    path.write_bytes(raw)
    doc = library.read_document('notes', 'a.md')
    assert doc['encoding'] == codec
    library.save_document('notes', 'a.md', doc['content'], doc['encoding'], doc['sha256'])
    assert path.read_bytes() == raw


def test_unknown_encoding_and_size_rejected(library, tmp_path):
    path = tmp_path / 'docs/a.md'
    path.write_bytes(b'\xff\x00broken')
    preview = library.read_document('notes', 'a.md')
    assert preview['encoding'] == 'unknown'
    assert preview['editable'] is False
    original = path.read_bytes()
    with pytest.raises(ValueError):
        library.save_document('notes', 'a.md', 'safe', 'utf-8', hashlib.sha256(original).hexdigest())
    assert path.read_bytes() == original
    path.write_bytes(b'A' * (512 * 1024 + 1))
    with pytest.raises(ValueError, match='size limit'):
        library.read_document('notes', 'a.md')


def test_encoding_failure_does_not_truncate(library, tmp_path):
    path = tmp_path / 'docs/a.md'
    path.write_bytes(b'\xff\xfe' + 'hi'.encode('utf-16-le'))
    doc = library.read_document('notes', 'a.md')
    with pytest.raises(ValueError):
        library.save_document('notes', 'a.md', 'good\x00bad', doc['encoding'], doc['sha256'])
    assert path.read_bytes() == b'\xff\xfe' + 'hi'.encode('utf-16-le')


def test_save_preserves_permissions(library, tmp_path):
    path = tmp_path / 'docs/a.md'
    path.write_text('original')
    path.chmod(0o640)
    previous = path.stat()
    item = library.read_document('notes', 'a.md')
    library.save_document('notes', 'a.md', 'updated', item['encoding'], item['sha256'])
    after = path.stat()
    assert after.st_mode & 0o777 == 0o640
    assert (after.st_uid, after.st_gid) == (previous.st_uid, previous.st_gid)


def test_no_extra_client_or_database_dependency(library):
    assert library.list_roots()['items'][0]['id'] == 'notes'


class PreviewTextEncodingTests(unittest.TestCase):
    def test_deterministic_codecs_roundtrip_bom(self):
        content = 'Hello 世界\r\nSecond line\r\n'
        variants = {
            'utf-8': content.encode('utf-8'),
            'utf-8-sig': b'\xef\xbb\xbf' + content.encode('utf-8'),
            'utf-16-le': b'\xff\xfe' + content.encode('utf-16-le'),
            'utf-16-be': b'\xfe\xff' + content.encode('utf-16-be'),
        }
        for codec, raw in variants.items():
            with self.subTest(codec=codec):
                self.assertEqual((content, codec), decode_text_bytes(raw))
                self.assertEqual({'content': content, 'encoding': codec, 'editable': True}, preview_text_bytes(raw))
                self.assertEqual(raw, encode_for_existing_file(content, codec, raw))
                new_content = content + 'New\n'
                payload = encode_for_existing_file(new_content, codec, raw)
                self.assertEqual(new_content, decode_text_bytes(payload)[0])

    def test_empty_ascii_unknown_and_binary(self):
        self.assertEqual(('', 'utf-8'), decode_text_bytes(b''))
        self.assertEqual(('ASCII', 'utf-8'), decode_text_bytes(b'ASCII'))
        for raw in (b'\xd6\xd0\xce\xc4', b'\xff', b'A\x00B',
                    b'A\x00B\x00', b'\xff\xfe\x00', b'\xff\xfe\x00\x00A'):
            with self.subTest(raw=raw):
                self.assertEqual('unknown', preview_text_bytes(raw)['encoding'])
                self.assertFalse(preview_text_bytes(raw)['editable'])
                with self.assertRaises(ValueError):
                    encode_for_existing_file('anything', 'utf-8', raw)

    def test_mismatch_and_unicode_error_dont_perform_writes(self):
        raw = b'\xef\xbb\xbfhello'
        with self.assertRaisesRegex(ValueError, 'encoding'):
            encode_for_existing_file('change', 'utf-8', raw)
        with self.assertRaises(UnicodeEncodeError):
            encode_for_existing_file('\ud800', 'utf-8-sig', raw)
        with self.assertRaisesRegex(ValueError, 'encoding'):
            encode_for_existing_file('change', 'gb18030', raw)

    def test_artifact_preview_strict_and_truncated(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'sample.txt'
            reg = SimpleNamespace(get_artifact_by_id=lambda _id: {
                'saved_path': str(target), 'original_name': 'sample.txt', 'artifact_id': 'aid'})
            artifact_service = SimpleNamespace(registry_service=reg, MAX_PREVIEW_TEXT_BYTES=204800)
            service = ArtifactPreviewService(artifact_service)
            for raw, codec, editable in [
                (b'hello\n', 'utf-8', True),
                (b'\xef\xbb\xbfhello', 'utf-8-sig', True),
                (b'\xff\xfeh\x00i\x00', 'utf-16-le', True),
                (b'\xfe\xff\x00h\x00i', 'utf-16-be', True),
                (b'\xd6\xd0\xce\xc4', 'unknown', False),
                (b'\x00\x01hello', 'unknown', False),
            ]:
                with self.subTest(codec=codec):
                    target.write_bytes(raw)
                    payload = service.build_preview_payload('aid')
                    self.assertEqual('text', payload['type'])
                    self.assertEqual(codec, payload['encoding'])
                    self.assertEqual(editable, payload['editable'])
                    self.assertEqual(False, payload['truncated'])
            target.write_bytes(b'A' * 204800 + b'B')
            payload = service.build_preview_payload('aid')
            self.assertTrue(payload['truncated'])
            self.assertFalse(payload['editable'])
            self.assertEqual('utf-8', payload['encoding'])

    def test_truncation_inside_multibyte_character_keeps_encoding(self):
        limit = 204800
        # Preview stops after one byte of a 3-byte UTF-8 code point.
        utf8 = b'A' * (limit - 1) + '界'.encode('utf-8') + b'END'
        utf8_bom = b'\xef\xbb\xbf' + b'A' * (limit - 4) + '界'.encode('utf-8') + b'END'
        # A UTF-16 preview can end after the leading surrogate of an emoji.
        for bom, codec in [(b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be')]:
            raw = bom + 'A'.encode(codec) * ((limit - 4) // 2) + '😀'.encode(codec) + 'END'.encode(codec)
            with self.subTest(codec=codec):
                self.assert_truncated_preview(raw, codec, limit, 'A' * ((limit - 4) // 2))
        self.assert_truncated_preview(utf8, 'utf-8', limit, 'A' * (limit - 1))
        self.assert_truncated_preview(utf8_bom, 'utf-8-sig', limit, 'A' * (limit - 4))

    def assert_truncated_preview(self, raw, codec, limit, expected_prefix):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'sample.txt'
            target.write_bytes(raw)
            reg = SimpleNamespace(get_artifact_by_id=lambda _id: {
                'saved_path': str(target), 'original_name': 'sample.txt', 'artifact_id': 'aid'})
            service = ArtifactPreviewService(SimpleNamespace(
                registry_service=reg, MAX_PREVIEW_TEXT_BYTES=limit))
            payload = service.build_preview_payload('aid')
            self.assertEqual(codec, payload['encoding'])
            self.assertTrue(payload['truncated'])
            self.assertFalse(payload['editable'])
            self.assertTrue(payload['content'].startswith(expected_prefix))
            self.assertNotIn('�', payload['content'])
            self.assertTrue(payload['content'].endswith('...(已截断)'))

    def test_truncation_does_not_hide_invalid_bytes_after_preview(self):
        limit = 204800
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'sample.txt'
            reg = SimpleNamespace(get_artifact_by_id=lambda _id: {
                'saved_path': str(target), 'original_name': 'sample.txt', 'artifact_id': 'aid'})
            service = ArtifactPreviewService(SimpleNamespace(
                registry_service=reg, MAX_PREVIEW_TEXT_BYTES=limit))
            for suffix in [b'\xff', b'\x00B', b'\xe7\x95']:
                with self.subTest(suffix=suffix):
                    target.write_bytes(b'A' * limit + suffix)
                    payload = service.build_preview_payload('aid')
                    self.assertTrue(payload['truncated'])
                    self.assertEqual('unknown', payload['encoding'])
                    self.assertFalse(payload['editable'])
            target.write_bytes(b'A' * limit)
            payload = service.build_preview_payload('aid')
            self.assertFalse(payload['truncated'])
            self.assertEqual('utf-8', payload['encoding'])
            self.assertTrue(payload['editable'])

    def test_artifact_save_preserves_bytes_and_failed_save_does_not_truncate(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'sample.txt'
            artifact = {'saved_path': str(target), 'original_name': 'sample.txt', 'artifact_id': 'aid'}
            api = WebArtifactApi.__new__(WebArtifactApi)
            api.get_artifact_by_id = lambda _id: artifact
            api.artifact_service = SimpleNamespace(guess_preview_type=lambda _name: 'text')
            for codec, raw in [
                ('utf-8', 'hello'.encode('utf-8')),
                ('utf-8-sig', b'\xef\xbb\xbfhello'),
                ('utf-16-le', b'\xff\xfeh\x00i\x00'),
                ('utf-16-be', b'\xfe\xff\x00h\x00i'),
            ]:
                with self.subTest(codec=codec):
                    target.write_bytes(raw)
                    api.update_artifact_content('aid', 'Hello 世界\r\n', codec)
                    self.assertEqual('Hello 世界\r\n', decode_text_bytes(target.read_bytes())[0])
                    preserved = target.read_bytes()
                    with self.assertRaises(UnicodeEncodeError):
                        api.update_artifact_content('aid', '\ud800', codec)
                    self.assertEqual(preserved, target.read_bytes())
                    with self.assertRaises(ValueError):
                        api.update_artifact_content('aid', 'bad', 'other')
                    self.assertEqual(preserved, target.read_bytes())
            target.write_bytes(b'\xd6\xd0\xce\xc4')
            with self.assertRaisesRegex(ValueError, 'unknown'):
                api.update_artifact_content('aid', 'change', 'utf-8')
            self.assertEqual(b'\xd6\xd0\xce\xc4', target.read_bytes())

    def test_client_save_preserves_bytes_and_fails_without_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'remote.txt'
            resolver = SimpleNamespace(require_existing_path_from_arg=lambda _path: str(target))
            service = FileSystemService(resolver)
            raw = b'\xfe\xff\x00h\x00i'
            target.write_bytes(raw)
            service.save_file_content(str(target), 'Edit\n', 'utf-16-be')
            saved = target.read_bytes()
            self.assertEqual('Edit\n', decode_text_bytes(saved)[0])
            with self.assertRaises(UnicodeEncodeError):
                service.save_file_content(str(target), '\ud800', 'utf-16-be')
            self.assertEqual(saved, target.read_bytes())
            with self.assertRaisesRegex(ValueError, 'encoding'):
                service.save_file_content(str(target), 'wrong', 'utf-8')
            self.assertEqual(saved, target.read_bytes())
            target.write_bytes(b'\xff\xff')
            with self.assertRaises(ValueError):
                service.save_file_content(str(target), 'wrong', 'utf-8')
            self.assertEqual(b'\xff\xff', target.read_bytes())
