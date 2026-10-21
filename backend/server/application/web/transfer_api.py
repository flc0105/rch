import hmac
import secrets
import threading

from core.protocol.message_types import MSG_TYPE_TRANSFER_CANCEL
from server.config.config import WEB_FILE_TRANSFER_PORT


class WebTransferApi:
    def __init__(self, transfer_service, server=None):
        self.transfer_service = transfer_service
        self.server = server
        self._browser_upload_grant_lock = threading.RLock()
        self._browser_upload_grants = {}
        self._browser_upload_cancel_events = {}

    def list_transfers(self, tab_id: str = ''):
        return self.transfer_service.list_transfers(tab_id=tab_id)

    def create_browser_upload_transfer(
        self,
        *,
        client_id: str,
        filename: str,
        total_bytes,
        destination_path: str = '',
        tab_id: str = '',
        origin: str = 'web_api',
        feature: str = 'remote_files',
    ):
        normalized_client_id = str(client_id or '').strip()
        normalized_filename = str(filename or '').strip()
        normalized_tab_id = str(tab_id or '').strip()
        if not normalized_client_id:
            raise ValueError('client_id is required')
        if not normalized_filename:
            raise ValueError('filename is required')
        if not normalized_tab_id:
            raise ValueError('tab_id is required')

        transfer = self.transfer_service.create_transfer(
            client_id=normalized_client_id,
            direction='server_to_client',
            filename=normalized_filename,
            destination_path=str(destination_path or '').strip(),
            tab_id=normalized_tab_id,
            stage='uploading_to_server',
            total_bytes=total_bytes,
            metadata={
                'source': 'remote_file_upload',
                'browser_stage': True,
            },
        )
        transfer_id = str(transfer.get('transfer_id') or '').strip()
        upload_token = secrets.token_urlsafe(32)
        with self._browser_upload_grant_lock:
            self._browser_upload_cancel_events[transfer_id] = threading.Event()
            self._browser_upload_grants[transfer_id] = {
                'token': upload_token,
                'client_id': normalized_client_id,
                'filename': normalized_filename,
                'total_bytes': total_bytes,
                'destination_path': str(destination_path or '').strip(),
                'tab_id': normalized_tab_id,
            }

        recorder = getattr(self.transfer_service, 'activity_recorder', None)
        if recorder is not None and self.server is not None:
            try:
                conn = self.server.get_target_connection_by_client_id(normalized_client_id)
            except Exception:
                conn = None
            if conn is not None:
                recorder.track(transfer_id, conn, action='upload_files', origin=origin, arguments={
                    'filename': normalized_filename, 'destination_path': destination_path,
                    'size': total_bytes, 'count': 1, 'source': feature,
                })

        return {
            **transfer,
            'browser_upload_port': WEB_FILE_TRANSFER_PORT,
            'browser_upload_path': f'/api/transfers/browser-upload/{transfer_id}/content',
            'browser_upload_token': upload_token,
        }

    def consume_browser_upload_grant(self, transfer_id: str, token: str) -> dict | None:
        normalized_id = str(transfer_id or '').strip()
        normalized_token = str(token or '').strip()
        if not normalized_id or not normalized_token:
            return None

        with self._browser_upload_grant_lock:
            grant = self._browser_upload_grants.get(normalized_id)
            if not grant:
                return None

            expected_token = str(grant.get('token') or '')
            if not expected_token or not hmac.compare_digest(normalized_token, expected_token):
                return None

            self._browser_upload_grants.pop(normalized_id, None)
            return {
                key: value
                for key, value in grant.items()
                if key != 'token'
            }

    def revoke_browser_upload_grant(self, transfer_id: str):
        normalized_id = str(transfer_id or '').strip()
        if not normalized_id:
            return
        with self._browser_upload_grant_lock:
            self._browser_upload_grants.pop(normalized_id, None)

    def is_browser_upload_cancel_requested(self, transfer_id: str) -> bool:
        normalized_id = str(transfer_id or '').strip()
        with self._browser_upload_grant_lock:
            event = self._browser_upload_cancel_events.get(normalized_id)
        return bool(event and event.is_set())

    def clear_browser_upload_runtime(self, transfer_id: str):
        normalized_id = str(transfer_id or '').strip()
        if not normalized_id:
            return
        with self._browser_upload_grant_lock:
            self._browser_upload_grants.pop(normalized_id, None)
            self._browser_upload_cancel_events.pop(normalized_id, None)

    def handle_client_disconnected(self, client_id: str):
        normalized_client_id = str(client_id or '').strip()
        if not normalized_client_id:
            return 0

        active = self.transfer_service.list_active_transfers_for_client(normalized_client_id)
        with self._browser_upload_grant_lock:
            for item in active:
                transfer_id = str(item.get('transfer_id') or '').strip()
                if not transfer_id:
                    continue
                self._browser_upload_grants.pop(transfer_id, None)
                event = self._browser_upload_cancel_events.get(transfer_id)
                if event is not None:
                    event.set()

        return self.transfer_service.fail_active_transfers_for_client(
            normalized_client_id,
            'Client disconnected during file transfer',
        )

    def cancel_transfer(self, transfer_id: str, *, tab_id: str = ''):
        normalized_id = str(transfer_id or '').strip()
        normalized_tab_id = str(tab_id or '').strip()
        current = self.transfer_service.get_transfer(normalized_id, tab_id=normalized_tab_id)
        if not current:
            raise ValueError('transfer not found')
        if current.get('state') != 'running':
            raise ValueError('transfer is no longer active')
        if current.get('cancel_supported') is False:
            raise ValueError('current transfer mode does not support cancellation')

        stage = str(current.get('stage') or '').strip().lower()
        self.transfer_service.mark_cancelling(normalized_id, tab_id=normalized_tab_id)

        metadata = current.get('metadata') if isinstance(current.get('metadata'), dict) else {}
        is_browser_upload = metadata.get('source') == 'remote_file_upload'

        if stage == 'uploading_to_server':
            with self._browser_upload_grant_lock:
                event = self._browser_upload_cancel_events.get(normalized_id)
                if event is not None:
                    event.set()
            cancelled = self.transfer_service.cancel_transfer(normalized_id, tab_id=normalized_tab_id)
            return cancelled or current

        if is_browser_upload and stage in ('preparing', 'cancelling'):
            cancelled = self.transfer_service.cancel_transfer(normalized_id, tab_id=normalized_tab_id)
            return cancelled or current

        if self.server is None:
            raise RuntimeError('server is not available for transfer cancellation')

        client_id = str(current.get('client_id') or '').strip()
        session = self.server.get_target_connection_by_client_id(client_id)
        session.send({
            'type': MSG_TYPE_TRANSFER_CANCEL,
            'transfer_id': normalized_id,
        })
        return self.transfer_service.get_transfer(normalized_id, tab_id=normalized_tab_id) or current

    def delete_recent_transfer(self, transfer_id: str, *, tab_id: str = ''):
        deleted = self.transfer_service.delete_recent_transfer(
            transfer_id,
            tab_id=str(tab_id or '').strip(),
        )
        if not deleted:
            raise ValueError('transfer not found')
        return {'transfer_id': str(transfer_id or '').strip(), 'deleted': True}

    def clear_recent_transfers(self, *, tab_id: str = ''):
        removed = self.transfer_service.clear_recent_transfers(
            tab_id=str(tab_id or '').strip(),
        )
        return {'removed': removed}

    def update_browser_upload_progress(
        self,
        transfer_id: str,
        *,
        transferred_bytes,
        total_bytes=None,
        tab_id: str = '',
    ):
        updated = self.transfer_service.update_progress(
            transfer_id,
            transferred_bytes,
            tab_id=str(tab_id or '').strip(),
            stage='uploading_to_server',
            total_bytes=total_bytes,
            expected_stage='uploading_to_server',
        )
        if updated is None:
            raise ValueError('transfer not found')
        return updated

    def mark_browser_upload_staged(
        self,
        transfer_id: str,
        *,
        total_bytes=None,
        tab_id: str = '',
    ):
        patch = {
            'stage': 'preparing',
            'metadata': {
                'browser_stage': False,
            },
        }
        if total_bytes is not None:
            patch['total_bytes'] = total_bytes
            patch['transferred_bytes'] = total_bytes

        updated = self.transfer_service.update_transfer(
            transfer_id,
            tab_id=str(tab_id or '').strip(),
            **patch,
        )
        if updated is None:
            raise ValueError('transfer not found')
        return updated


    def fail_upload_transfer(self, transfer_id: str, error: str, *, tab_id: str = ''):
        updated = self.transfer_service.update_transfer(
            transfer_id,
            tab_id=str(tab_id or '').strip(),
            state='failed',
            stage='failed',
            error=str(error or 'Upload failed').strip(),
            metadata={
                'browser_stage': False,
            },
        )
        if updated is None:
            raise ValueError('transfer not found')
        return updated

    def fail_browser_upload_transfer(self, transfer_id: str, error: str, *, tab_id: str = ''):
        self.clear_browser_upload_runtime(transfer_id)
        updated = self.transfer_service.update_transfer(
            transfer_id,
            tab_id=str(tab_id or '').strip(),
            expected_stage='uploading_to_server',
            state='failed',
            stage='failed',
            error=str(error or 'Browser upload failed').strip(),
            metadata={
                'browser_stage': False,
            },
        )
        if updated is None:
            raise ValueError('transfer not found')
        return updated
