"""Remote Files semantic Activity contract: no Quick, post-send only, one per UI operation."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from client.commands.common.services.filesystem.file_system_service import FileSystemService
from core.protocol.structured_arg_codec import decode_structured_arg
from server.application.artifact.remote_file_service import WebRemoteFileService


class MemoryOrchestrator:
    def __init__(self):
        self.pending = {}
        self.entries = {}
        self.quick = []
        self.prepared = 0

    def begin_remote_files_execution(self, conn, action, arguments, command_name, command, *, origin='web_ui'):
        self.prepared += 1
        activity_id = f'file-action-{self.prepared}'
        self.pending[activity_id] = {
            'kind': 'remote_files', 'action': action, 'origin': origin,
            'invocation': {'arguments': arguments}, 'resolved': {
                'command_type': 'command', 'command_name': command_name,
                **({'command': command} if command is not None else {})},
            'status': 'pending', 'result': {'output_records': []},
            'machine_id': conn.session_info.machine_id,
        }
        return activity_id

    def confirm(self, activity_id):
        if activity_id:
            self.entries[activity_id] = self.pending.pop(activity_id)
            self.entries[activity_id]['status'] = 'running'

    def append_output(self, conn, activity_id, status, text):
        if activity_id in self.entries:
            self.entries[activity_id]['result']['output_records'].append({'status': status, 'text': text})

    def finalize_execution(self, conn, activity_id, ok, status=''):
        if activity_id in self.entries:
            self.entries[activity_id]['status'] = status or ('success' if ok else 'error')

    def discard_execution(self, conn, activity_id):
        self.pending.pop(activity_id, None)


class FakeExecution:
    def __init__(self, orchestrator, *, report=None, send=False, text='OK', fail=None):
        self.history_orchestrator = orchestrator
        self.session = SimpleNamespace(session_info=SimpleNamespace(machine_id='machine-A', client_id='c1'))
        self.report = report
        self.sent = send
        self.text = text
        self.fail = fail
        self.calls = []

    def get_connection(self, client_id):
        return self.session

    def _execute(self, command, kwargs):
        self.calls.append((command, kwargs))
        if self.fail == 'pre_send':
            raise RuntimeError('cannot send')
        self.history_orchestrator.confirm(kwargs['history_entry_id'])
        if self.fail == 'post_send':
            raise RuntimeError('Client failed')
        return self.report

    def run_foreground_text_command(self, client_id, command, **kwargs):
        self._execute(command, kwargs)
        return self.text

    def run_foreground_json_command(self, client_id, command, **kwargs):
        return self._execute(command, kwargs)


def setup_service(**kwargs):
    orchestrator = MemoryOrchestrator()
    runner = FakeExecution(orchestrator, **kwargs)
    return WebRemoteFileService(runner, artifact_service=None), orchestrator, runner


@pytest.mark.parametrize('invoke,action,command', [
    (lambda s: s.create_directory('c1', '/tmp/newdir'), 'create_directory', 'mkdir_path'),
    (lambda s: s.delete_path('c1', '/tmp/a'), 'delete_files', 'delete_path'),
    (lambda s: s.rename_path('c1', '/tmp/a', 'b'), 'rename_files', 'rename_path'),
    (lambda s: s.save_file_content('c1', '/tmp/a', 'very-sensitive-file-content'), 'save_file', 'save_file_content'),
])
def test_single_mutation_has_one_semantic_entry(invoke, action, command):
    service, orch, runner = setup_service()
    invoke(service)
    assert len(orch.entries) == 1
    entry = next(iter(orch.entries.values()))
    assert entry['action'] == action
    assert entry['status'] == 'success'
    assert entry['resolved']['command_name'] == command
    assert entry['machine_id'] == 'machine-A'
    assert runner.calls[0][1]['task_type'] == 'remote_file'
    assert runner.calls[0][1]['source'] == 'web_remote_file'
    assert not orch.quick
    if action == 'save_file':
        assert 'command' not in entry['resolved']
        assert 'content' not in entry['invocation']['arguments']
        assert 'very-sensitive-file-content' not in str(entry)


@pytest.mark.parametrize('result,status,raises', [
    ({'status': 1, 'total': 3, 'succeeded': 3, 'failed': 0, 'message': 'Deleted 3 of 3 items'}, 'success', False),
    ({'status': 1, 'total': 3, 'succeeded': 2, 'failed': 1, 'message': 'Deleted 2 of 3 items\nErrors:\n a: denied'}, 'error', False),
    ({'status': 0, 'total': 3, 'succeeded': 0, 'failed': 3, 'message': 'Deleted 0 of 3 items\nErrors:\n failed'}, 'error', True),
])
def test_batch_one_activity_with_partial_or_total_failure(result, status, raises):
    service, orch, runner = setup_service(report=result)
    if raises:
        with pytest.raises(RuntimeError, match='Deleted 0'):
            service.delete_paths('c1', ['a', 'b', 'c'])
    else:
        assert service.delete_paths('c1', ['a', 'b', 'c'])['message'] == result['message']
    entry = next(iter(orch.entries.values()))
    assert len(orch.entries) == 1
    assert entry['status'] == status
    assert entry['result']['output_records'][0]['text'] == result['message']
    assert len(orch.pending) == 0
    assert 'activity_report' not in decode_structured_arg(runner.calls[0][0].split(' ', 1)[1])


@pytest.mark.parametrize('operation,action', [('copy','copy_files'),('move','move_files')])
def test_paste_reports_as_one_semantic_operation(operation, action):
    report = {'status':1, 'total':2, 'succeeded':1, 'failed':1, 'message':'Copied 1 of 2 items'}
    service, orch, _ = setup_service(report=report)
    service.paste_paths('c1',['a','b'],'/tmp/destination',operation)
    assert next(iter(orch.entries.values()))['action'] == action
    assert next(iter(orch.entries.values()))['status'] == 'error'


@pytest.mark.parametrize('action', ['create_zip_from_paths','extract_zip'])
def test_archive_action_emits_one_entry(action):
    service, orch, _ = setup_service(report={'archive_path':'/tmp/out.zip'})
    if action == 'create_zip_from_paths':
        service.create_zip_from_paths('c1',['a'], '/tmp')
        expected = 'create_archive'
    else:
        service.extract_zip('c1', '/tmp/in.zip', '/tmp')
        expected = 'extract_archive'
    assert len(orch.entries) == 1
    assert next(iter(orch.entries.values()))['action'] == expected


@pytest.mark.parametrize('error,expected', [('pre_send', 0), ('post_send', 1)])
def test_dispatch_boundary_and_error(error, expected):
    service, orch, _ = setup_service(fail=error)
    with pytest.raises(RuntimeError):
        service.delete_path('c1', '/tmp/test')
    assert len(orch.entries) == expected
    assert not orch.pending
    if expected:
        assert next(iter(orch.entries.values()))['status'] == 'error'


def test_invalid_parameter_does_not_prepare_or_persist():
    service, orch, _ = setup_service()
    with pytest.raises(ValueError):
        service.rename_path('c1', '', 'new')
    assert orch.prepared == 0


def test_save_error_never_persists_sensitive_content():
    service, orch, runner = setup_service(fail='post_send')
    with pytest.raises(RuntimeError):
        service.save_file_content('c1','/tmp/a','secret-payload')
    entry = next(iter(orch.entries.values()))
    assert 'secret-payload' not in str(entry)
    assert entry['status'] == 'error'
    # Actual client dispatch still includes the full content, only Activity redacts it.
    assert 'secret-payload' not in str(runner.calls[0][1])


def test_client_batch_reports_are_structured_not_guessed_from_english(tmp_path):
    first = tmp_path/'first'; first.write_text('1')
    missing = tmp_path/'missing'
    fs = FileSystemService(SimpleNamespace(require_existing_path_from_arg=lambda name: (
        name if Path(name).exists() else (_ for _ in ()).throw(FileNotFoundError(name)))))
    report = fs.delete_paths([str(first), str(missing)]).to_dict()
    assert (report['total'], report['succeeded'], report['failed']) == (2,1,1)
    assert report['status'] == 1
    assert not first.exists()
    second = tmp_path/'second'; second.write_text('2')
    report = fs.paste_paths([str(second), str(missing)], str(tmp_path/'target'), 'copy').to_dict()
    assert report['failed'] == 2 and report['succeeded'] == 0 and report['status'] == 0


def test_web_api_origin_is_not_mislabeled_as_ui():
    service, orch, _ = setup_service()
    service.rename_path('c1', '/tmp/a', 'b', origin='web_api')
    assert next(iter(orch.entries.values()))['origin'] == 'web_api'


def test_batch_empty_paths_are_errors_not_current_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'keep').write_text('keep')
    fs = FileSystemService(SimpleNamespace(require_existing_path_from_arg=lambda name: (
        str(tmp_path) if not name else str(tmp_path / name))))
    report = fs.delete_paths(['']).to_dict()
    assert report['succeeded'] == 0 and report['failed'] == 1
    assert (tmp_path / 'keep').exists()
