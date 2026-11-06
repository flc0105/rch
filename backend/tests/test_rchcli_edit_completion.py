"""Client and Server registration for RCHCLI remote edit path completion."""

import unittest
import ast
from pathlib import Path

from core.command_completion.models import CompletionContext
from client.commands.common.services.completion.command_completion_providers import (
    EditPathCommandCompletionProvider,
)
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


class RuntimeConfigService:
    def list_config_items(self):
        return []


class CommandHost:
    def __init__(self):
        self.path_resolver = PathResolver()
        self.file_system_service = FileSystemService()
        self.runtime_config_service = RuntimeConfigService()


class EditCompletionTests(unittest.TestCase):
    def test_server_remote_client_completion_allowlist_includes_edit(self):
        source = (
            Path(__file__).resolve().parents[1]
            / 'server/application/completion/command_completion_providers.py'
        ).read_text(encoding='utf-8')
        module = ast.parse(source)
        provider = next(
            node for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == 'RemoteClientCommandCompletionProvider'
        )
        assignment = next(
            node for node in provider.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == 'command_names' for target in node.targets)
        )
        self.assertIn('edit', ast.literal_eval(assignment.value))

    def test_client_edit_provider_completes_directories_and_files(self):
        host = CommandHost()
        provider = EditPathCommandCompletionProvider(
            path_resolver=host.path_resolver,
            file_system_service=host.file_system_service,
        )
        context = CompletionContext(
            command_name='edit',
            argument_text='/Users/flc/',
            current_token='',
        )

        items = provider.complete(context)

        self.assertEqual(host.path_resolver.lookups, ['/Users/flc/'])
        self.assertEqual(
            [(item.insert_text, item.kind) for item in items],
            [
                ('edit /Users/flc/Desktop', 'directory'),
                ('edit /Users/flc/notes.txt', 'file'),
            ],
        )

    def test_client_completion_service_registers_edit_provider(self):
        host = CommandHost()
        result = ClientCommandCompletionService(host).complete({
            'raw_input': 'edit /Users/flc/',
            'cursor_position': len('edit /Users/flc/'),
        })
        self.assertEqual(
            [item['insert_text'] for item in result['items']],
            ['edit /Users/flc/Desktop', 'edit /Users/flc/notes.txt'],
        )


if __name__ == '__main__':
    unittest.main()
