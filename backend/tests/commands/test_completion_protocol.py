from types import SimpleNamespace

from client.commands.common.services.completion.command_completion_service import ClientCommandCompletionService
from client.connection.message_dispatcher import ClientInboundMessageDispatcher
from client.connection.message_router import ClientInboundMessageRouter
from core.command_completion.models import CompletionSpec
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.protocol.message_types import MSG_TYPE_COMPLETION
from core.utils.decorator import desc
from server.connection.client_session import ClientSession
from server.application.web.command_catalog_api import WebCommandCatalogApi
from core.command_completion.parser import CommandCompletionParser


class PathResolver:
    def __init__(self):
        self.lookups = []

    def require_existing_directory_from_arg(self, path):
        self.lookups.append(path)
        return path or '/cwd'


class FileSystemService:
    def list_child_paths(self, directory):
        return {'entries': [
            {'name': 'docs', 'path': directory.rstrip('/') + '/docs', 'is_dir': True},
            {'name': 'readme.txt', 'path': directory.rstrip('/') + '/readme.txt', 'is_dir': False},
        ]}


class Commands:
    def __init__(self):
        self.path_resolver = PathResolver()
        self.file_system_service = FileSystemService()
        self._registry = SimpleNamespace(_entries={
            'image_info': {'spec': ArgumentCommandSpec(name='image_info', options=[
                ArgumentOptionSpec(name='path', positional_index=0,
                                   completion=CompletionSpec('filesystem', ('file', 'directory'))),
            ])},
            'sqlite_query': {'spec': ArgumentCommandSpec(name='sqlite_query', options=[
                ArgumentOptionSpec(name='db', completion=CompletionSpec('filesystem', ('file', 'directory'))),
                ArgumentOptionSpec(name='query'),
            ])},
        })

    def get_argument_command_registry(self):
        return self._registry

    @desc('Change working directory', completion=CompletionSpec('filesystem', ('directory',)))
    def cd(self, path=''):
        return 1, path


def test_shell_like_and_acmd_annotations_select_filesystem_provider():
    commands = Commands()
    service = ClientCommandCompletionService(commands)

    cd = service.complete({'raw_input': 'cd ', 'cursor_position': 3})
    assert [item['kind'] for item in cd['items']] == ['directory']
    assert all(item['insert_text'].startswith('cd ') for item in cd['items'])

    positional = service.complete({'raw_input': 'acmd image_info /tmp/', 'cursor_position': 21})
    assert [item['kind'] for item in positional['items']] == ['directory', 'file']
    assert all(item['insert_text'].startswith('acmd image_info /tmp/') for item in positional['items'])

    named = service.complete({'raw_input': 'acmd sqlite_query --db /tmp/', 'cursor_position': 29})
    assert [item['kind'] for item in named['items']] == ['directory', 'file']
    assert all('--db /tmp/' in item['insert_text'] for item in named['items'])

    inline = service.complete({
        'raw_input': 'acmd sqlite_query --db=/tmp/',
        'cursor_position': len('acmd sqlite_query --db=/tmp/'),
    })
    assert [item['kind'] for item in inline['items']] == ['directory', 'file']
    assert all('--db=/tmp/' in item['insert_text'] for item in inline['items'])


def test_completion_message_is_immediate_and_returns_structured_result():
    assert MSG_TYPE_COMPLETION in ClientInboundMessageDispatcher.IMMEDIATE_MESSAGE_TYPES

    class Executor:
        def complete_command_completion(self, payload):
            assert payload['raw_input'] == 'cd '
            return {'items': [{'name': 'cd docs', 'kind': 'directory'}]}

    class Connection:
        runtime = SimpleNamespace(command_executor=Executor())

        def __init__(self):
            self.events = []

        def send_event(self, request_id, event):
            self.events.append((request_id, event))

    connection = Connection()
    ClientInboundMessageRouter(connection).handle_completion_message({'id': 91, 'raw_input': 'cd '})
    assert connection.events == [(91, {
        'event_type': 'completed', 'status': 'success', 'message': '',
        'data': {'items': [{'name': 'cd docs', 'kind': 'directory'}]},
    })]


def test_server_completion_message_bypasses_foreground_and_activity_dispatch():
    class Transport:
        address = 'test'

        def __init__(self):
            self.session = None
            self.messages = []

        def send(self, data):
            self.messages.append(data)
            self.session.runtime.pending_results.deliver(data['id'], {
                'event_type': 'completed', 'status': 'success', 'message': '',
                'data': {'items': []},
            })

        def close(self):
            pass

    class Adapter:
        def __init__(self):
            self.calls = []

        def prepare_dispatch(self, *args):
            self.calls.append('prepare')

        def dispatch(self, *args):
            self.calls.append('dispatch')

    transport = Transport()
    session = ClientSession(transport, info={'id': 'client-1'})
    transport.session = session
    adapter = Adapter()
    session.context.command_dispatch_adapter = adapter

    chunks = list(session.send_completion({'raw_input': 'cd ', 'cursor_position': 3}))
    assert len(chunks) == 1
    assert chunks[0].event['event_type'] == 'completed'
    assert transport.messages[0]['type'] == 'completion'
    assert 'text' not in transport.messages[0]
    assert adapter.calls == []
    assert session.get_foreground_task() is None


def test_web_api_forwards_common_ops_completion_spec_override():
    class Service:
        def __init__(self):
            self.calls = []

        def complete(self, **kwargs):
            self.calls.append(kwargs)
            return {'context': {}, 'items': []}

    api = WebCommandCatalogApi.__new__(WebCommandCatalogApi)
    api.command_completion_service = Service()
    spec = {'provider': 'filesystem', 'kinds': ['file', 'directory']}
    api.get_command_completions(
        'client-1', raw_input='cat /tmp/', cursor_position=9,
        max_results=50, completion_spec=spec,
    )
    assert api.command_completion_service.calls == [{
        'client_id': 'client-1', 'raw_input': 'cat /tmp/',
        'cursor_position': 9, 'max_results': 50, 'completion_spec': spec,
    }]


def test_completion_parser_converts_browser_utf16_cursor_to_python_offset():
    context = CommandCompletionParser().parse(
        raw_input='cd 😀/folder', cursor_position=6,
    )
    assert context.cursor_position == 5
    assert context.current_token == '😀/'


def test_completion_context_uses_shared_resolver_for_quoted_current_token():
    context = CommandCompletionParser().parse(
        raw_input='acmd image_info --path="/tmp/a b"',
    )
    assert context.command_name == 'acmd'
    assert context.argument_text == 'image_info --path="/tmp/a b"'
    assert context.current_token == 'b"'


def test_command_candidates_expose_handshake_completion_metadata_without_copying_spec_fields():
    class Server:
        def get_target_connection_by_client_id(self, client_id):
            return SimpleNamespace(session_info=SimpleNamespace(command_manifest=[
                {'name': 'cd', 'completion': {'provider': 'filesystem', 'kinds': ['directory']}},
            ]))

    api = WebCommandCatalogApi.__new__(WebCommandCatalogApi)
    api.server = Server()
    candidates = api._get_client_command_candidates(api.server.get_target_connection_by_client_id('client'))
    assert candidates[0]['completion'] == {'provider': 'filesystem', 'kinds': ['directory']}
    assert set(candidates[0]['completion']) == {'provider', 'kinds'}
