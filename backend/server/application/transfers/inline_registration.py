"""Validate file transfer registration against a live command/Control request."""
import os
import uuid

from core.protocol.control import ControlDomain, ClipboardAction
from core.protocol.message_types import MSG_TYPE_TRANSFER_REGISTER, MSG_TYPE_CONTROL, MSG_TYPE_COMMAND, MSG_TYPE_ACMD
from core.transfer_settings import FileTransferMode


def register_inline_transfer(transfers, artifacts, session, payload):
    """A command/Clipboard Control can register only within its live request."""
    transfer_id = payload.get('transfer_id')
    reply = {'type': MSG_TYPE_TRANSFER_REGISTER, 'transfer_id': transfer_id, 'accepted': False}
    try:
        if not isinstance(transfer_id, str) or uuid.UUID(hex=transfer_id).hex != transfer_id:
            raise ValueError('Invalid transfer ID')
        command_id = payload.get('command_id')
        request = session.runtime.pending_results.get_request(command_id) if type(command_id) is int else None
        if not request:
            raise ValueError('File transfer requires an active request')
        direction = payload.get('direction')
        mode = FileTransferMode(payload.get('file_transfer_mode')).value
        filename = payload.get('filename')
        if (not isinstance(filename, str) or not filename or filename in ('.', '..')
                or '/' in filename or '\\' in filename or '\x00' in filename):
            raise ValueError('Invalid transfer filename')
        clipboard = request.get('type') == MSG_TYPE_CONTROL and request.get('domain') == ControlDomain.CLIPBOARD
        source_path = ''
        total = payload.get('total_bytes')
        if direction == 'client_to_server':
            if not (request.get('type') in (MSG_TYPE_COMMAND, MSG_TYPE_ACMD) or
                    (clipboard and request.get('action') == ClipboardAction.GET)):
                raise ValueError('Request does not support artifact upload')
            source_path = str(payload.get('source_path') or '')
        elif direction == 'server_to_client':
            # A Client must not be able to name an arbitrary Server file.
            url = payload.get('source_url')
            items = (request.get('payload') or {}).get('items') or []
            if (not clipboard or request.get('action') != ClipboardAction.SET
                    or not isinstance(url, str) or not any(isinstance(item, dict) and item.get('url') == url for item in items)):
                raise PermissionError('File is not staged for this Clipboard request')
            parts = url.split('/')
            if len(parts) != 5 or parts[:3] != ['', 'api', 'upload-tmp']:
                raise ValueError('Invalid staged file URL')
            source_path = artifacts.get_upload_temp_file_path(parts[3], parts[4])
            total = os.path.getsize(source_path)
        else:
            raise ValueError('Invalid transfer direction')
        info = session.session_info
        foreground = session.get_foreground_task() or {}
        tab_id = str((request.get('extra') or {}).get('tab_id') or '')
        if foreground.get('command_id') == command_id:
            tab_id = foreground.get('tab_id') or tab_id
        transfers.create_transfer(
            transfer_id=transfer_id, client_id=info.client_id, direction=direction,
            filename=filename, hostname=info.hostname, source_path=source_path,
            total_bytes=total, tab_id=tab_id,
            cancel_supported=mode != FileTransferMode.HTTP_SIMPLE.value,
            progress_supported=(direction == 'server_to_client' or mode != FileTransferMode.HTTP_SIMPLE.value),
            metadata={'transport': 'client_transfer_manager', 'file_transfer_mode': mode,
                      'source': 'clipboard' if clipboard else 'client_command',
                      'source_command_id': command_id},
        )
        reply['accepted'] = True
    except Exception as exc:
        reply['error'] = str(exc)
    session.send(reply)

