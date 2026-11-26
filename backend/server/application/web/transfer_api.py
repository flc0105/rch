import hmac
import secrets
import threading



class WebTransferApi:
    def __init__(self, transfer_service, server=None, *, command_execution_api=None):
        self.transfer_service = transfer_service
        self.server = server
        self.command_execution_api = command_execution_api
        self._browser_upload_grant_lock = threading.RLock()
        self._browser_upload_grants = {}
        self.transfer_service.terminal_callback = self.clear_browser_upload_runtime

    def list_transfers(self, tab_id: str = '', *, limit: int = 20, offset: int = 0,
                       machine_id: str = ''):
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

        if conflict_policy is not None and conflict_policy not in ('stop', 'replace', 'keep_both'):
            raise ValueError('Invalid upload conflict policy')
        if batch_id:
            if not isinstance(batch_id, str) or len(batch_id) > 128 or not batch_id.isascii():
                raise ValueError('Invalid upload batch')
            if not (1 <= int(batch_total) <= 1000 and 0 <= int(batch_index) < int(batch_total)):
                raise ValueError('Invalid upload batch size')

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
                'operation_id': operation_id,
                **({'batch_id': batch_id, 'batch_total': int(batch_total), 'batch_index': int(batch_index)} if batch_id else {}),
            },
        )
        transfer_id = str(transfer.get('transfer_id') or '').strip()
        upload_token = secrets.token_urlsafe(32)
        with self._browser_upload_grant_lock:
            self._browser_upload_grants[transfer_id] = {
                'token': upload_token,
                'client_id': normalized_client_id,
                'filename': normalized_filename,
                'total_bytes': total_bytes,
                'destination_path': str(destination_path or '').strip(),
                'conflict_policy': conflict_policy if conflict_policy is not None else 'stop',
                'operation_id': operation_id,
                'batch_id': batch_id,
                'tab_id': normalized_tab_id,
            }

        if self.is_browser_upload_cancel_requested(transfer_id):
            self.clear_browser_upload_runtime(transfer_id)
            raise ValueError("Upload is no longer active")
        return {
            **transfer,
            'browser_upload_path': f'/api/transfers/browser-upload/{transfer_id}/content',
            'browser_upload_token': upload_token,
            **({'operation_id': operation_id} if operation_id else {}),
        }

    def start_browser_upload_batch(self, *, client_id, batch_id, tab_id,
                                   destination_path, total_files, folder_count):
        client_id = str(client_id or '').strip()
        batch_id = str(batch_id or '').strip()
        if not client_id or not tab_id or not batch_id or len(batch_id) > 128 or not batch_id.isascii():
            raise ValueError('Invalid upload batch')
        total_files = int(total_files)
        folder_count = int(folder_count)
        if not (0 <= total_files <= 1000 and 0 <= folder_count <= 10000) or not (total_files or folder_count):
            raise ValueError('Invalid upload batch size')
        if self.command_execution_api is None:
            raise RuntimeError('Upload execution is unavailable')
        batch = self.transfer_service.start_batch(
            batch_id=batch_id, client_id=client_id, tab_id=tab_id,
            destination_path=str(destination_path or '').strip(),
            total_files=total_files, folder_count=folder_count)
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
        folder_count = int(folder_count)
        if folder_count < 0 or folder_count > 10000:
            raise ValueError('Invalid folder count')
        return self.transfer_service.finalize_batch(
            client_id=client_id, batch_id=batch_id, tab_id=tab_id,
            folder_count=folder_count, error=str(error or '')[:256])

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
