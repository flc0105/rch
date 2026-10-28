"""All command candidate APIs use name for inserted text (no template mirror)."""
from types import SimpleNamespace
from unittest.mock import Mock

from core.command_completion.models import CompletionCandidate
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
from server.application.web.command_catalog_api import WebCommandCatalogApi


def test_builtin_candidates_have_only_name_for_insertion():
    candidates = SERVER_COMMAND_REGISTRY.candidates()
    assert candidates
    assert all('template' not in item and item['name'] for item in candidates)
    assert all(item['name'].strip() for item in candidates)
    assert any(item['name'].startswith('script') for item in candidates)


def test_command_candidate_aggregation_uses_name_for_dedup_and_server_precedence():
    api = WebCommandCatalogApi(SimpleNamespace(get_target_connection_by_client_id=lambda _id: None), Mock())
    session = SimpleNamespace(session_info=SimpleNamespace(command_manifest=[
        {'name': 'acmd help', 'source': 'client'},
        {'name': 'script', 'source': 'client'},  # Server builtin wins.
        {'name': 'acmd ping', 'source': 'client'},
    ]))
    api.server.get_target_connection_by_client_id = lambda _client_id: session
    server_commands = [
        {'name': 'script ', 'source': 'server', 'group': 'server'},
        {'name': 'alias', 'source': 'server', 'group': 'server'},
        {'name': 'acmd ping', 'source': 'server', 'group': 'server'},
    ]
    api.command_executor_factory.create.return_value.get_command_candidates.return_value = server_commands
    candidates = api.get_command_candidates('client-1')
    assert all('template' not in item for item in candidates)
    assert [item['name'] for item in candidates].count('acmd help') == 1
    assert 'script' not in [item['name'] for item in candidates]
    assert [item['name'] for item in candidates].count('acmd ping') == 1
    assert candidates[0]['source'] == 'client'


def test_dynamic_completion_serialization_name_matches_inserted_text():
    candidate = CompletionCandidate(
        title='Script display label', insert_text='script exec ./some/path.py',
        name='old semantic name', source='server_script',
    )
    payload = candidate.to_dict()
    assert payload['name'] == 'script exec ./some/path.py'
    assert payload['title'] == 'Script display label'
    assert payload['value'] == payload['name'] == payload['insert_text']
    assert 'template' not in payload
