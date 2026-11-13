"""Control envelope and Remote File Browser use typed parameters end to end."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from client.runtime.control_dispatcher import ClientControlDispatcher
from client.runtime.execution.runtime import ExecutionRuntime
from client.remote_files.manager import RemoteFilesManager

def dispatcher():
    socket = SimpleNamespace()
    return ClientControlDispatcher(ExecutionRuntime(socket), {'remote_files': RemoteFilesManager().execute})
from core.protocol.control import build_control_message
from server.application.artifact.remote_file_service import WebRemoteFileService
from server.connection.channel.session_command_channel import ClientSessionCommandChannel


def test_control_message_is_flat_and_fails_closed():
    packet = build_control_message(43, 'job', 'start', {
        'job_name': 'demo', 'execution_mode': 'inproc', 'params': {'threshold': 5},
    })
    assert packet == {
        'type': 'control', 'id': 43, 'domain': 'job', 'action': 'start',
        'payload': {'job_name': 'demo', 'execution_mode': 'inproc', 'params': {'threshold': 5}},
    }
    channel = ClientSessionCommandChannel(SimpleNamespace())
    assert channel.build_command_payload('', 'control', payload={'paths': ['/x']},
                                         domain='remote_files', action='delete_paths') == {
        'type': 'control', 'id': 1, 'domain': 'remote_files',
        'action': 'delete_paths', 'payload': {'paths': ['/x']},
    }
    for domain, action, payload in [('', 'start', {}), ('job', '', {}), ('job', 'start', 'text')]:
        with pytest.raises(ValueError):
            build_control_message(1, domain, action, payload)
    with pytest.raises(ValueError):
        channel.build_command_payload('shell pwd', domain='job', action='start')
    with pytest.raises(ValueError):
        channel.build_command_payload('', 'job_control', payload={})


def test_remote_file_browser_calls_control_with_typed_payload(tmp_path):
    control = dispatcher()
    calls = []

    class Remote:
        def run_foreground_control(self, client_id, domain, action, payload, **kwargs):
            calls.append((client_id, domain, action, payload, kwargs))
            return control.execute(1, domain, action, payload)

    browser = WebRemoteFileService(Remote(), None)
    folder = tmp_path / 'created'
    created = browser.create_directory('device-1', str(folder))
    assert folder.is_dir() and 'Directory created' in created['message']
    assert calls[-1][1:4] == ('remote_files', 'create_directory', {'path': str(folder)})
    assert calls[-1][4]['task_type'] == 'remote_file'

    source = folder / 'source.txt'
    source.write_text('abc', encoding='utf-8')
    result = browser.browse_directory('device-1', str(folder), page_size=50)
    assert any(row['name'] == 'source.txt' for row in result['entries'])
    assert calls[-1][2] == 'browse_directory' and isinstance(calls[-1][3], dict)

    browser.save_file_content('device-1', str(source), 'hello', encoding='utf-8')
    assert source.read_text() == 'hello'
    assert calls[-1][2] == 'save_file' and calls[-1][3]['content'] == 'hello'
    browser.rename_path('device-1', str(source), 'renamed.txt')
    renamed = folder / 'renamed.txt'
    assert renamed.read_text() == 'hello'
    assert calls[-1][2] == 'rename_path'

    zip_result = browser.create_zip_from_paths('device-1', [str(renamed)], str(tmp_path), 'bundle_example.zip')
    assert zip_result['archive_name'] == 'bundle_example.zip'
    assert (tmp_path / 'bundle_example.zip').is_file()
    listing = browser.peek_zip('device-1', str(tmp_path / 'bundle_example.zip'))
    assert isinstance(listing, dict) and listing['entry_count'] >= 1

    copied_dir = tmp_path / 'copies'
    copied_dir.mkdir()
    preflight = browser.paste_paths('device-1', [str(renamed)], str(copied_dir), inspect=True)
    assert isinstance(preflight, dict) and calls[-1][2] == 'paste_paths'
    copied = browser.paste_paths('device-1', [str(renamed)], str(copied_dir))
    assert copied['succeeded'] == 1 and (copied_dir / 'renamed.txt').read_text() == 'hello'
    assert calls[-1][3]['operation'] == 'copy'

    extracted_dir = tmp_path / 'extracted'
    extracted_dir.mkdir()
    archive_path = str(tmp_path / 'bundle_example.zip')
    preview = browser.extract_zip('device-1', archive_path, str(extracted_dir), inspect=True)
    assert isinstance(preview, dict) and calls[-1][2] == 'extract_archive'
    extract_result = browser.extract_zip('device-1', archive_path, str(extracted_dir))
    assert isinstance(extract_result, dict) and (Path(extract_result['extracted_to']) / 'renamed.txt').is_file()
    assert calls[-1][3]['conflict_policy'] == 'stop'
    upload_inspect = browser.inspect_upload('device-1', str(extracted_dir), 'next.txt')
    assert isinstance(upload_inspect, dict) and calls[-1][2] == 'inspect_upload'

    deleted = browser.delete_paths('device-1', [str(renamed)])
    assert deleted['message'] and not renamed.exists()
    assert calls[-1][2] == 'delete_paths'
    assert not any('__json__:' in str(call) for call in calls)


def test_invalid_action_does_not_touch_files(tmp_path):
    control = dispatcher()
    path = tmp_path / 'keep.txt'
    path.write_text('keep')
    status, text = control.execute(1, 'remote_files', 'delete_everything', {'path': str(path)},
    )
    assert status == 0 and 'Unsupported' in text and path.exists()
    status, text = control.execute(1, 'unknown', 'stop', {})
    assert status == 0 and 'Unsupported' in text
