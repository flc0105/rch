import hashlib
import hmac
import json
import secrets
import threading
import time

from server.application.transfers.upload_plan import validate_upload_size


class WebTransferApi:
    def __init__(self, transfer_service, server=None, *, command_execution_api=None):
        self.transfer_service = transfer_service
        self.server = server
        self.command_execution_api = command_execution_api
        self._browser_upload_grant_lock = threading.RLock()
        self._submission_lock = threading.RLock()
        self._browser_upload_grants = {}
        self.transfer_service.terminal_callback = self.clear_browser_upload_runtime

    def list_transfers(self, tab_id: str = '', *, limit: int = 20, offset: int = 0,
                       machine_id: str = ''):
        self.expire_browser_upload_grants()
        return self.transfer_service.list_transfers(
            tab_id=tab_id, limit=limit, offset=offset, machine_id=machine_id,
        )

    def create_browser_upload_transfer(
        self,
        *,
        client_id: str,
        filename: str,
        total_bytes,
        destination_path: str = '',
        conflict_policy=None,
        tab_id: str = '',
        operation_id: str = '',
        batch_id: str = '',
        batch_total=0,
        batch_index=0,
    ):
        normalized_client_id = str(client_id or '').strip()
        normalized_filename = str(filename or '')
        normalized_tab_id = str(tab_id or '').strip()
        if not normalized_client_id:
            raise ValueError('client_id is required')
        if (not normalized_filename or normalized_filename != normalized_filename.strip()
                or normalized_filename in ('.', '..') or any(ch in normalized_filename for ch in ('/', '\\'))
                or any(ord(ch) < 32 for ch in normalized_filename)):
            raise ValueError('Invalid upload filename')
        validate_upload_size(total_bytes)
        if not normalized_tab_id:
            raise ValueError('tab_id is required')

        if conflict_policy is not None and conflict_policy not in ('stop', 'replace', 'keep_both'):
            raise ValueError('Invalid upload conflict policy')
        if batch_id:
            if not isinstance(batch_id, str) or len(batch_id) > 128 or not batch_id.isascii():
                raise ValueError('Invalid upload batch')
            if type(batch_total) is not int or type(batch_index) is not int or not (1 <= batch_total <= 1000 and 0 <= batch_index < batch_total):
                raise ValueError('Invalid upload batch size')

        request_key = f'batch:{batch_id}:{batch_index}' if batch_id else f'operation:{operation_id}' if operation_id else ''
        spec = {'client_id': normalized_client_id, 'filename': normalized_filename,
                'total_bytes': total_bytes, 'destination_path': str(destination_path or '').strip(),
                'conflict_policy': conflict_policy or 'stop', 'operation_id': operation_id,
                'batch_id': batch_id, 'batch_total': batch_total, 'batch_index': batch_index,
                'tab_id': normalized_tab_id}
        fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.expire_browser_upload_grants()
        with self._submission_lock:
            existing = self.transfer_service.find_tab_transfer_by_metadata(
                normalized_tab_id, 'browser_submission_key', request_key) if request_key else None
            if existing:
                if existing['metadata'].get('browser_submission_fingerprint') != fingerprint:
                    raise ValueError('Upload submission does not match its original request')
                transfer_id = existing['transfer_id']
                with self._browser_upload_grant_lock:
                    grant = self._browser_upload_grants.get(transfer_id)
                    upload_token = grant['token'] if grant else ''
                if upload_token and not self.is_browser_upload_cancel_requested(transfer_id):
                    return self._upload_grant_response(existing, upload_token, operation_id)
                status = self.get_browser_upload_status(transfer_id, tab_id=normalized_tab_id)
                if status['state'] == 'completed' or (status['state'] == 'running' and status['accepted']):
                    return status
                raise ValueError('Upload submission already exists; check Transfers before retrying')

            transfer = self.transfer_service.create_transfer(
                client_id=normalized_client_id, direction='server_to_client', filename=normalized_filename,
                destination_path=spec['destination_path'], tab_id=normalized_tab_id,
                stage='uploading_to_server', total_bytes=total_bytes,
                metadata={
                    'source': 'remote_file_upload', 'browser_stage': True,
                    'browser_upload_accepted': False, 'browser_submission_key': request_key,
                    'browser_submission_fingerprint': fingerprint, 'conflict_policy': spec['conflict_policy'],
                    'operation_id': operation_id,
                    **({'batch_id': batch_id, 'batch_total': batch_total, 'batch_index': batch_index} if batch_id else {}),
                },
            )
            transfer_id = transfer['transfer_id']
            upload_token = secrets.token_urlsafe(32)
            with self._browser_upload_grant_lock:
                self._browser_upload_grants[transfer_id] = {**spec, 'token': upload_token,
                                                            'expires_at': time.monotonic() + 300}
            if self.is_browser_upload_cancel_requested(transfer_id):
                self.clear_browser_upload_runtime(transfer_id)
                raise ValueError('Upload is no longer active')
            return self._upload_grant_response(transfer, upload_token, operation_id)

    @staticmethod
    def _upload_grant_response(transfer, token, operation_id):
        return {**transfer, 'browser_upload_path': f"/api/transfers/browser-upload/{transfer['transfer_id']}/content",
                'browser_upload_token': token, **({'operation_id': operation_id} if operation_id else {})}

    def start_browser_upload_batch(self, *, client_id, batch_id, tab_id,
                                   destination_path, files, directories):
        client_id = str(client_id or '').strip()
        batch_id = str(batch_id or '').strip()
        if not client_id or not tab_id or not batch_id or len(batch_id) > 128 or not batch_id.isascii():
            raise ValueError('Invalid upload batch')
        if self.command_execution_api is None:
            raise RuntimeError('Upload execution is unavailable')
        arguments = dict(batch_id=batch_id, client_id=client_id, tab_id=tab_id,
                         destination_path=str(destination_path or '').strip(), files=files, directories=directories)
        with self._submission_lock:
            recovered = self.transfer_service.recover_batch_submission(**arguments)
            if recovered is not None:
                return recovered
            batch = self.transfer_service.start_batch(**arguments)
            try:
                task = self.command_execution_api.submit_web_upload_batch(batch)
                if task.get('task_id'):
                    self.transfer_service.bind_batch_task(batch_id, task['task_id'])
            except Exception as exc:
                self.transfer_service.finalize_batch(batch_id=batch_id, client_id=client_id,
                    tab_id=tab_id, folder_count=0, error=str(exc))
                raise
            return {**batch, **task}

    def get_batch_members(self, batch_id, tab_id=''):
        return {'items': self.transfer_service.list_batch_members(batch_id, tab_id=tab_id)}

    def finalize_browser_upload_batch(self, *, client_id: str, batch_id: str,
                                      tab_id: str, folder_count=0, error: str = ''):
        client_id = str(client_id or '').strip()
        batch_id = str(batch_id or '').strip()
        if not client_id or not tab_id or not batch_id or len(batch_id) > 128 or not batch_id.isascii():
            raise ValueError('Invalid browser upload batch')
        if type(folder_count) is not int or folder_count < 0 or folder_count > 10000:
            raise ValueError('Invalid folder count')
        return self.transfer_service.finalize_batch(
            client_id=client_id, batch_id=batch_id, tab_id=tab_id,
            folder_count=folder_count, error=str(error or '')[:256])

    def consume_browser_upload_grant(self, transfer_id: str, token: str) -> dict | None:
        normalized_id = str(transfer_id or '').strip()
        normalized_token = str(token or '').strip()
        if not normalized_id or not normalized_token:
            return None

        self.expire_browser_upload_grants()
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
                if key not in ('token', 'expires_at')
            }

    def expire_browser_upload_grants(self):
        now = time.monotonic()
        with self._browser_upload_grant_lock:
            expired = [(tid, grant['tab_id']) for tid, grant in self._browser_upload_grants.items()
                       if grant['expires_at'] <= now]
            for tid, _ in expired:
                self._browser_upload_grants.pop(tid, None)
        for tid, tab_id in expired:
            self.transfer_service.update_transfer(tid, tab_id=tab_id, expected_stage='uploading_to_server',
                state='failed', stage='failed', error='Browser upload grant expired')

    def revoke_browser_upload_grant(self, transfer_id: str):
        normalized_id = str(transfer_id or '').strip()
        if not normalized_id:
            return
        with self._browser_upload_grant_lock:
            self._browser_upload_grants.pop(normalized_id, None)

    def is_browser_upload_cancel_requested(self, transfer_id: str) -> bool:
        current = self.transfer_service.get_transfer(transfer_id)
        return not current or current['state'] != 'running' or current['stage'] == 'cancelling'

    def clear_browser_upload_runtime(self, transfer_id: str):
        self.revoke_browser_upload_grant(transfer_id)

    def handle_client_disconnected(self, client_id: str):
        return self.transfer_service.fail_active_transfers_for_client(
            str(client_id or '').strip(), 'Client disconnected during file transfer')

    def cancel_transfer(self, transfer_id: str, *, tab_id: str = ''):
        return self.transfer_service.cancel_operation(
            str(transfer_id or '').strip(), tab_id=str(tab_id or '').strip(),
            connection_lookup=self.server.get_target_connection_by_client_id if self.server else None)

    def delete_recent_transfer(self, transfer_id: str, *, tab_id: str = ''):
        deleted = self.transfer_service.delete_recent_transfer(
            transfer_id,
            tab_id=str(tab_id or '').strip(),
        )
        if not deleted:
            raise ValueError('transfer not found')
        return {'transfer_id': str(transfer_id or '').strip(), 'deleted': True}

    def clear_recent_transfers(self, *, tab_id: str = '', machine_id: str = ''):
        removed = self.transfer_service.clear_recent_transfers(
            tab_id=str(tab_id or '').strip(), machine_id=str(machine_id or '').strip(),
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
        self.get_browser_upload_status(transfer_id, tab_id=tab_id)
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

    def get_browser_upload_status(self, transfer_id, *, tab_id):
        current = self.transfer_service.get_tab_transfer(transfer_id, tab_id)
        if not current or 'browser_upload_accepted' not in current['metadata']:
            raise FileNotFoundError('Browser upload status not found')
        metadata = current['metadata']
        return {'transfer_id': transfer_id, 'client_id': current['client_id'],
                'state': current['state'], 'stage': current['stage'], 'error': current['error'],
                'accepted': bool(metadata['browser_upload_accepted'] or current['state'] == 'completed'
                                 or metadata.get('transport') == 'client_transfer_manager'),
                'task_id': metadata.get('task_id', '')}

    def mark_browser_upload_accepted(self, transfer_id, *, tab_id, task_id=''):
        metadata = {'browser_upload_accepted': True}
        if task_id:
            metadata['task_id'] = task_id
        return self.transfer_service.update_transfer(transfer_id, tab_id=tab_id, metadata=metadata)

    def fail_browser_upload_transfer(self, transfer_id: str, error: str, *, tab_id: str = ''):
        self.get_browser_upload_status(transfer_id, tab_id=tab_id)
        # Once the one-use grant is consumed, the receiving Server owns failure
        # reporting. A late browser response must not terminate its intake.
        with self._browser_upload_grant_lock:
            grant = self._browser_upload_grants.pop(transfer_id, None)
        if grant is None:
            return self.transfer_service.get_tab_transfer(transfer_id, tab_id)
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
