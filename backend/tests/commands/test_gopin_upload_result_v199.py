"""Gopin's declared list route and Upload's single terminal Result contract."""
import json
from types import SimpleNamespace

import pytest

from core.utils.command_output import OutputFormat, render_result_payload
from server.application.command.command_execution_event import CommandExecutionEvent
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY


def invocation(command, tail=''):
    return SERVER_COMMAND_REGISTRY.parse_invocation(command, tail)


@pytest.mark.parametrize('tail', ['', 'list', '--json', 'list --json'])
def test_gopin_list_routes_match(tail):
    parsed = invocation('gopin', tail)
    assert parsed.action == 'list'
    assert parsed.arguments['json'] == ('--json' in tail)


def test_gopin_jump_preserves_existing_unquoted_whitespace():
    for tail in ('saved work dir', 'go saved work dir'):
        parsed = invocation('gopin', tail)
        assert parsed.action == 'go'
        assert parsed.arguments['command'] == 'saved work dir'
        assert parsed.output_format == OutputFormat.TEXT


def test_gopin_list_rejects_undeclared_option():
    with pytest.raises(ValueError, match='Unknown option'):
        invocation('gopin', 'list --unknown')


def test_gopin_result_projection_and_jump():
    from server.application.command.builtin_command_support import PinnedPathBuiltinSupport
    support = PinnedPathBuiltinSupport.__new__(PinnedPathBuiltinSupport)
    support.list_pinned_paths = lambda: [
        {'display_name': 'saved work dir', 'path': '/tmp/work'},
        {'display_name': 'other', 'path': '/tmp/other'},
    ]
    support._get_machine_id = lambda: 'machine-1'
    support.pinned_path_store = SimpleNamespace(
        get_item_by_name=lambda _machine, name: {'path': '/tmp/work'}
        if name == 'saved work dir' else None)
    support.command_processor_factory = lambda: lambda text: lambda: iter([(1, 'cwd=/tmp/work')])
    text_default = list(support.gopin(invocation('gopin')))
    text_explicit = list(support.gopin(invocation('gopin', 'list')))
    assert text_default == text_explicit
    assert 'saved work dir' in text_default[0][1]
    json_default = list(support.gopin(invocation('gopin', '--json')))
    json_explicit = list(support.gopin(invocation('gopin', 'list --json')))
    assert json_default == json_explicit
    assert json.loads(json_default[0][1]) == [
        {'name': 'saved work dir', 'path': '/tmp/work'},
        {'name': 'other', 'path': '/tmp/other'},
    ]
    assert len(list(support.gopin(invocation('gopin', 'saved work dir')))) == 2
    jump = list(support.gopin(invocation('gopin', 'go saved work dir')))
    assert jump[0][0] == 1 and 'gopin saved work dir' in jump[0][1]
    assert jump[1] == (1, 'cwd=/tmp/work')
    missing = list(support.gopin(invocation('gopin', 'non-existent')))
    assert missing[0][0] == 0 and 'Pinned path not found' in missing[0][1]


def test_gopin_empty_list_text_and_json():
    from server.application.command.builtin_command_support import PinnedPathBuiltinSupport
    support = PinnedPathBuiltinSupport.__new__(PinnedPathBuiltinSupport)
    support.list_pinned_paths = lambda: []
    assert 'No saved pinned paths' in list(support.gopin(invocation('gopin')))[0][1]
    assert json.loads(list(support.gopin(invocation('gopin', '--json')))[0][1]) == []


def upload_support(tmp_path, events):
    from server.application.command.builtin_command_support import UploadBuiltinSupport
    source = tmp_path / 'example.txt'
    source.write_text('hello')
    support = UploadBuiltinSupport(
        conn=SimpleNamespace(get_foreground_task=lambda: {}),
        remote_execution_service=SimpleNamespace(iter_upload_events=lambda *a, **kw: iter(events)),
        history_entry_id_provider=lambda: '',
    )
    return support, invocation('upload', str(source))


def test_upload_single_success_result_without_duplicate_progress(tmp_path):
    events = [
        CommandExecutionEvent.started('upload example.txt'),
        CommandExecutionEvent.progress('', payload={'stage': 'staged'}),
        CommandExecutionEvent.completed(True),
    ]
    support, inv = upload_support(tmp_path, events)
    rows = list(support.upload(inv))
    assert len(rows) == 1
    assert rows[0] == (1, 'File transferred successfully: example.txt')
    assert rows[0].event['event_type'] == 'completed'
    assert rows[0].event['status'] == 'success'
    assert 'Path:' not in str(rows) and 'Size:' not in str(rows)


def test_upload_failure_one_error_no_false_success(tmp_path):
    events = [CommandExecutionEvent.started('upload example.txt'),
              CommandExecutionEvent.error('Remote disk full'),
              CommandExecutionEvent.completed(False)]
    support, inv = upload_support(tmp_path, events)
    assert list(support.upload(inv)) == [(0, 'Remote disk full')]


def test_upload_cancellation_keeps_transfer_protocol(tmp_path):
    events = [CommandExecutionEvent.cancelled('cancelled', payload={'transfer_id': 't-1'}),
              CommandExecutionEvent.completed(False)]
    support, inv = upload_support(tmp_path, events)
    rows = list(support.upload(inv))
    assert len(rows) == 1
    assert rows[0][0] == 0
    assert rows[0][1]['event_type'] == 'cancelled'
    assert rows[0][1]['transfer_id'] == 't-1'
    assert rows[0][1]['failure_reason'] == 'cancelled'


def test_upload_missing_file_does_not_start_transfer(tmp_path):
    from server.application.command.builtin_command_support import UploadBuiltinSupport
    support = UploadBuiltinSupport(None, None, lambda: '')
    with pytest.raises(FileNotFoundError, match='File does not exist'):
        list(support.upload(invocation('upload', str(tmp_path / 'missing.txt'))))
