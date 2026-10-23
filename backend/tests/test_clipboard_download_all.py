import os
import re
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import Mock, patch
from types import SimpleNamespace

from client.commands.common.services.filesystem.archive_service import ArchiveService


class ClipboardDownloadAllTests(unittest.TestCase):
    def test_archive_temp_root_for_directory_and_multi_path_zip(self):
        from client.commands.common.services.filesystem.path_resolver import PathResolver
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = os.path.join(tmp, 'rch_client_temp', 'archive_temp')
            os.makedirs(temp_root)
            source_dir = os.path.join(tmp, 'source')
            os.makedirs(source_dir)
            with open(os.path.join(source_dir, 'one.txt'), 'w', encoding='utf-8') as output:
                output.write('one')
            service = ArchiveService(path_resolver=Mock(spec=PathResolver))
            service.path_resolver.validate_directory_exists.return_value = source_dir
            with patch('client.commands.common.services.filesystem.archive_service.get_temp_category_dir',
                       return_value=temp_root):
                for path in (service.create_zip_archive(source_dir),
                             service.create_zip_from_paths([os.path.join(source_dir, 'one.txt')])):
                    try:
                        self.assertEqual(os.path.dirname(os.path.dirname(path)), temp_root)
                        self.assertTrue(zipfile.is_zipfile(path))
                    finally:
                        shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    def test_clipboard_staging_temp_except_macos_gui_path(self):
        from client.clipboard.manager import ClipboardManager
        with tempfile.TemporaryDirectory() as tmp:
            temp_stage = os.path.join(tmp, 'rch_client_temp', 'clipboard_staging')
            for alias, expected in (('ios', temp_stage), ('win', temp_stage),
                                    ('linux', temp_stage), ('mac', os.path.join(tmp, 'gui', '.rch', 'clipboard_staging'))):
                with self.subTest(alias=alias), \
                     patch('client.clipboard.manager.get_local_identity',
                           return_value=SimpleNamespace(os_alias=alias)), \
                     patch('client.clipboard.manager.get_temp_category_dir', return_value=temp_stage), \
                     patch('client.clipboard.manager.ClientApiClient'), \
                     patch.object(ClipboardManager, '_get_macos_console_identity',
                                  return_value={'home': os.path.join(tmp, 'gui'), 'uid': 501}), \
                     patch.object(ClipboardManager, '_build_adapter'), \
                     patch.object(ClipboardManager, '_clear_staging_on_startup'):
                    manager = ClipboardManager(connection=Mock())
                    self.assertEqual(manager.staging_dir, expected)

    def test_multi_path_download_uses_auto_zip_name(self):
        service = ArchiveService(path_resolver=None)
        name = service.build_download_archive_name(['/tmp/a.txt', '/tmp/b.txt'])
        self.assertRegex(name, r'^bundle_\d{8}-\d{6}\.zip$')

    def test_multi_path_download_creates_one_zip_with_all_roots(self):
        service = ArchiveService(path_resolver=None)
        with tempfile.TemporaryDirectory() as source_dir:
            first = os.path.join(source_dir, 'first.txt')
            second_dir = os.path.join(source_dir, 'second')
            second = os.path.join(second_dir, 'nested.txt')
            os.makedirs(second_dir)
            with open(first, 'w', encoding='utf-8') as file_obj:
                file_obj.write('first')
            with open(second, 'w', encoding='utf-8') as file_obj:
                file_obj.write('second')

            archive_path = service.create_zip_from_paths([first, second_dir])
            try:
                self.assertRegex(os.path.basename(archive_path), r'^bundle_\d{8}-\d{6}\.zip$')
                with zipfile.ZipFile(archive_path, 'r') as archive:
                    self.assertEqual(
                        {'first.txt', 'second/nested.txt'},
                        set(archive.namelist()),
                    )
            finally:
                shutil.rmtree(os.path.dirname(archive_path), ignore_errors=True)

    def test_clipboard_ui_wires_download_all_to_zip_api(self):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        dialog_path = os.path.join(project_root, 'frontend', 'src', 'components', 'ClipboardDialog.vue')
        api_path = os.path.join(project_root, 'frontend', 'src', 'api', 'clipboardApi.js')

        with open(dialog_path, 'r', encoding='utf-8') as file_obj:
            dialog = file_obj.read()
        with open(api_path, 'r', encoding='utf-8') as file_obj:
            api = file_obj.read()

        self.assertIn('Download All', dialog)
        self.assertIn('async downloadAllRemoteFiles()', dialog)
        self.assertIn('downloadRemoteClipboardFiles(', dialog)
        self.assertIn("Preparing ZIP download", dialog)
        self.assertIn('export function downloadRemoteClipboardFiles', api)
        self.assertIn('/remote-files/download-zip', api)
        self.assertRegex(api, re.compile(r"jsonRequestOptions\('POST', \{ paths, archive_name: '' \}, headers\)"))


if __name__ == '__main__':
    unittest.main()
