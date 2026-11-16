"""Client filesystem completion can be selected by the shared CompletionSpec."""

import unittest

from client.commands.common.services.completion.command_completion_service import (
    ClientCommandCompletionService,
)


class PathResolver:
    def __init__(self):
        self.lookups = []

    def require_existing_directory_from_arg(self, value):
        self.lookups.append(value)
        return value or '/'


class FileSystemService:
    def list_child_paths(self, directory):
        return {
            'entries': [
                {'name': 'Desktop', 'path': directory.rstrip('/') + '/Desktop', 'is_dir': True},
                {'name': 'notes.txt', 'path': directory.rstrip('/') + '/notes.txt', 'is_dir': False},
            ]
        }


class CommandHost:
    def __init__(self):
        self.path_resolver = PathResolver()
        self.file_system_service = FileSystemService()


class EditCompletionTests(unittest.TestCase):
    def test_client_completion_service_accepts_common_ops_override(self):
        host = CommandHost()
        result = ClientCommandCompletionService(host).complete({
            'raw_input': 'edit /Users/flc/',
            'cursor_position': len('edit /Users/flc/'),
            'completion': {'provider': 'filesystem', 'kinds': ['file', 'directory']},
        })
        self.assertEqual(host.path_resolver.lookups, ['/Users/flc/'])
        self.assertEqual(
            [(item['insert_text'], item['kind']) for item in result['items']],
            [
                ('edit /Users/flc/Desktop', 'directory'),
                ('edit /Users/flc/notes.txt', 'file'),
            ],
        )

    def test_completion_spec_filters_file_or_directory(self):
        host = CommandHost()
        service = ClientCommandCompletionService(host)
        directory_only = service.complete({
            'raw_input': 'rmdir ', 'cursor_position': 6,
            'completion': {'provider': 'filesystem', 'kinds': ['directory']},
        })
        self.assertEqual([item['kind'] for item in directory_only['items']], ['directory'])
        file_only = service.complete({
            'raw_input': 'cat ', 'cursor_position': 4,
            'completion': {'provider': 'filesystem', 'kinds': ['file']},
        })
        self.assertEqual([item['kind'] for item in file_only['items']], ['file'])

    def test_browser_utf16_cursor_is_converted_once_before_filesystem_slicing(self):
        host = CommandHost()
        raw_input = 'cat 😀/'
        result = ClientCommandCompletionService(host).complete({
            'raw_input': raw_input,
            'cursor_position': 7,  # c a t space = 4 units, emoji = 2, slash = 1
            'completion': {'provider': 'filesystem', 'kinds': ['file', 'directory']},
        })
        self.assertEqual(host.path_resolver.lookups, ['😀/'])
        self.assertTrue(all(item['insert_text'].startswith('cat 😀/') for item in result['items']))


if __name__ == '__main__':
    unittest.main()
