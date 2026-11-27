"""Submit browser/Artifact uploads to the common Web task lifecycle."""
from dataclasses import dataclass
from functools import partial

from server.application.tasks.task_service import WebExecutionTaskRequest
from server.application.tasks.task_types import TASK_TYPE_UPLOAD


@dataclass(frozen=True)
class UploadTaskRequest:
    local_path: str
    display_name: str
    remote_path: str = ''
    transfer_id: str = ''
    conflict_policy: str | None = None
    batch_id: str = ''


class UploadTaskService:
    def __init__(self, task_service, uploads):
        self.task_service = task_service
        self.uploads = uploads

    def _events(self, request, context):
        yield from self.uploads.iter_upload_operation(
            context.session, request.local_path, remote_path=request.remote_path,
            display_name=request.display_name, transfer_id=request.transfer_id,
            conflict_policy=request.conflict_policy, batch_id=request.batch_id,
            history_entry_id=context.history_entry_id, source=context.source,
            task_id=context.task_id, command=context.command, tab_id=context.tab_id,
        )

    def _submit(self, client_id, request, *, tab_id='', operation_id=''):
        return self.task_service.submit(WebExecutionTaskRequest(
            client_id=client_id, command=self.uploads.format_display_command(request.display_name),
            task_type=TASK_TYPE_UPLOAD, events=partial(self._events, request),
            tab_id=tab_id, source='web', use_foreground_guard=False,
            metadata={'operation_id': operation_id} if operation_id else {},
            cancel_handler=partial(self.uploads.cancel_task, transfer_id=request.transfer_id),
        ))

    def submit_batch(self, batch):
        batch_id = batch['batch_id']
        request = UploadTaskRequest('', f"{batch['total_files']} file(s) -> {batch['destination_path']}",
                                    batch['destination_path'], batch['transfer_id'], batch_id=batch_id)
        self.uploads.open_browser_batch(batch_id)
        try:
            return self._submit(batch['client_id'], request, tab_id=batch['tab_id'], operation_id=batch_id)
        except Exception:
            self.uploads.close_browser_batch(batch_id)
            raise

    def submit_upload(self, client_id, local_path, display_name, remote_path='', *, tab_id='',
                      transfer_id='', conflict_policy=None, operation_id='', batch_id=''):
        request = UploadTaskRequest(local_path, display_name, remote_path, transfer_id, conflict_policy, batch_id)
        if batch_id:
            return self.uploads.enqueue_browser_upload(
                batch_id, client_id, local_path, display_name=display_name, remote_path=remote_path,
                tab_id=tab_id, transfer_id=transfer_id, conflict_policy=conflict_policy)
        return self._submit(client_id, request, tab_id=tab_id, operation_id=operation_id)
