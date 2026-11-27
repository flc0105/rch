"""Browser batches use Transfers; standalone uploads retain Web Task results."""

from types import SimpleNamespace

from server.application.execution.execution_context import TaskExecutionContext
from server.application.execution.upload_execution_service import UploadExecutionService
from server.application.tasks.task_runner import WebTaskRunner
from server.application.tasks.task_service import WebTaskService
from server.application.execution.upload_task_service import UploadTaskService


def test_standalone_web_upload_retains_native_task_events():
    service = object.__new__(WebTaskService)
    captured = []
    service.submit = lambda request: captured.append(request) or {'task_id': 'single'}
    uploads = UploadExecutionService(None, None)
    UploadTaskService(service, uploads).submit_upload('client', '/tmp/file', 'example.jpg', tab_id='tab')
    assert len(captured) == 1
    request = captured[0]
    assert request.command == '[Remote Upload] example.jpg'
    assert request.use_foreground_guard is False
    assert 'result_presentation' not in request.metadata

    emitted = []
    runner = object.__new__(WebTaskRunner)
    runner.event_bus = SimpleNamespace(publish=lambda *args, **kwargs: emitted.append(args[0]))
    runner.task_store = SimpleNamespace(get_task=lambda _: {'status': 'success'})
    session = SimpleNamespace(get_foreground_task=lambda: None)
    context = TaskExecutionContext(session=session, command=request.command,
                                   task_id='single', client_id='client', tab_id='tab')
    runner._publish_task_result(context, 1, 'transferred')
    runner._publish_task_complete(context)
    assert emitted == ['command_result', 'command_complete']


def test_batch_member_real_transfer_lifecycle_keeps_hostname_and_failure_reason(tmp_path, monkeypatch):
    from pathlib import Path
    from server.application.transfers.transfer_service import TransferService
    from server.persistence.rch_database import RchDatabase
    from server.web.event_bus import WebEventBus

    class Artifacts:
        def __init__(self, path):
            self.path = path
            self.cleaned = []
        def is_upload_temp_file(self, path):
            return True
        def stage_local_file(self, path, display_name=''):
            dest = self.path / f'copy-{display_name}'
            dest.write_bytes(Path(path).read_bytes())
            return str(dest), display_name
        def build_upload_temp_download_relative_url(self, path):
            return '/api/upload-tmp/test/' + Path(path).name
        def cleanup_upload_temp_file(self, path):
            self.cleaned.append(path)
            Path(path).unlink(missing_ok=True)

    db = RchDatabase(str(tmp_path / 'rch.db'))
    transfer_service = TransferService(WebEventBus(), db)
    artifacts = Artifacts(tmp_path)
    original = tmp_path / 'original.jpg'
    original.write_bytes(b'some file contents')
    info = SimpleNamespace(client_id='c1', hostname='mac-host')
    session = SimpleNamespace(session_info=info)
    executor = UploadExecutionService(None, SimpleNamespace(get_connection=lambda _: session),
                                      artifact_service=artifacts, transfer_service=transfer_service)
    try:
        for success in (True, False):
            original.write_bytes(b'some file contents')
            batch_id = 'batch-ok' if success else 'batch-fail'
            transfer_service.start_batch(batch_id=batch_id, client_id='c1', tab_id='tab',
                                         destination_path='/dest', files=[{'relative_path':'original.jpg','size':len(b'some file contents'),'conflict_policy':'stop'}], directories=[])
            transfer = transfer_service.create_transfer(client_id='c1', tab_id='tab',
                filename='original.jpg', direction='server_to_client', destination_path='/dest', total_bytes=len(b'some file contents'),
                metadata={'batch_id': batch_id, 'batch_total': 1, 'batch_index': 0})
            def send(payload):
                if success:
                    transfer_service.complete_transfer(payload['transfer_id'])
                else:
                    raise PermissionError('Read-only destination')
            session.send = send
            executor.open_browser_batch(batch_id)
            executor.enqueue_browser_upload(batch_id, 'c1', str(original), display_name='original.jpg',
                                                remote_path='/dest', tab_id='tab',
                                                transfer_id=transfer['transfer_id'], conflict_policy='stop')
            events = list(executor.iter_upload_operation('c1', batch_id=batch_id, tab_id='tab', task_id='task'))
            assert events[-1].event_type == 'completed'
            batch = transfer_service.batches.get(batch_id)
            assert batch['hostname'] == 'mac-host'
            if success:
                assert batch['state'] == 'completed'
                assert batch['error'] == ''
            else:
                assert batch['state'] == 'failed'
                assert 'Read-only destination' in batch['error']
                assert 'original.jpg' in batch['error']
        assert len(artifacts.cleaned) == 2  # Each already staged file is cleaned once.
    finally:
        db.close_thread_connection()


def test_batch_submission_creates_exactly_one_native_upload_task():
    from server.application.web.command_execution_api import WebCommandExecutionApi
    opened, requests, queued = [], [], []
    task_service = object.__new__(WebTaskService)
    task_service.submit = lambda request: requests.append(request) or {'task_id': 'parent'}
    remote = SimpleNamespace(open_browser_batch=opened.append,
        format_display_command=UploadExecutionService.format_display_command, cancel_task=lambda *_: None,
        enqueue_browser_upload=lambda *args, **kwargs: queued.append((args, kwargs)) or {})
    uploads = UploadTaskService(task_service, remote)
    api = WebCommandExecutionApi(task_service, upload_task_service=uploads, task_runner=None)
    uploads.submit_batch({'batch_id': 'b', 'total_files': 2, 'destination_path': '/dest',
        'client_id': 'c', 'tab_id': 'tab', 'transfer_id': 'batch:b'})
    for i in range(2):
        api.submit_web_upload('c', f'/tmp/f{i}', f'f{i}', '/dest', tab_id='tab',
                              transfer_id=f'f{i}', batch_id='b')
    assert opened == ['b'] and len(requests) == 1 and len(queued) == 2
    assert requests[0].metadata['operation_id'] == 'b'
    assert callable(requests[0].events) and callable(requests[0].cancel_handler)
    assert requests[0].use_foreground_guard is False


def test_batch_queue_applies_backpressure_and_dispatches_sequentially(tmp_path):
    import threading
    from server.application.transfers.transfer_service import TransferService
    from server.persistence.rch_database import RchDatabase
    from server.web.event_bus import WebEventBus
    db = RchDatabase(str(tmp_path / 'rch.db'))
    transfers = TransferService(WebEventBus(), db)
    session = SimpleNamespace(session_info=SimpleNamespace(client_id='c', hostname='device'))
    executor = UploadExecutionService(None, SimpleNamespace(get_connection=lambda _: session),
        artifact_service=SimpleNamespace(cleanup_upload_temp_file=lambda _: None), transfer_service=transfers)
    transfers.start_batch(batch_id='b', client_id='c', tab_id='tab', destination_path='/dest', files=[{'relative_path':f'f{i}','size':1,'conflict_policy':'stop'} for i in range(2)], directories=[])
    for i in range(2):
        transfers.create_transfer(client_id='c', tab_id='tab', filename=f'f{i}', direction='server_to_client', destination_path='/dest', total_bytes=1,
            transfer_id=f'f{i}', metadata={'batch_id': 'b', 'batch_total': 2, 'batch_index': i})
    executor.open_browser_batch('b')
    def enqueue(i):
        executor.enqueue_browser_upload('b', 'c', f'/tmp/f{i}', display_name=f'f{i}', remote_path='/dest',
            tab_id='tab', transfer_id=f'f{i}', conflict_policy='stop')
    enqueue(0)
    entered, accepted = threading.Event(), threading.Event()
    def producer():
        try:
            entered.set(); enqueue(1); accepted.set()
        finally:
            db.close_thread_connection()
    thread = threading.Thread(target=producer, daemon=True); thread.start()
    assert entered.wait(1) and not accepted.wait(.05)
    order = []
    def execute(target, local_path, *, transfer_id, **kwargs):
        order.append(transfer_id)
        transfers.complete_transfer(transfer_id)
        yield from ()
    executor.iter_upload_events = execute
    events = list(executor.iter_upload_operation('c', batch_id='b', tab_id='tab', task_id='parent'))
    thread.join(1)
    assert accepted.is_set() and order == ['f0', 'f1']
    assert events[-1].event_type == 'completed'
    assert transfers.get_batch('b')['state'] == 'completed'
    assert 'b' not in executor._batch_queues
    db.close_thread_connection()
