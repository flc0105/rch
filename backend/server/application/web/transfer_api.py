class WebTransferApi:
    """HTTP-facing transfer operations; browser intake belongs to its domain service."""

    def __init__(self, transfer_service, browser_upload_service, connection_lookup):
        self._transfers = transfer_service
        self._uploads = browser_upload_service
        self._connection_lookup = connection_lookup

    def list_transfers(self, tab_id='', *, limit=20, offset=0, machine_id=''):
        return self._uploads.list_transfers(tab_id=tab_id, limit=limit, offset=offset, machine_id=machine_id)

    def create_browser_upload_transfer(self, **request):
        result = self._uploads.create_browser_upload_transfer(**request)
        if result.get('browser_upload_token'):
            return {**result, 'browser_upload_path': f"/api/transfers/browser-upload/{result['transfer_id']}/content"}
        return result

    def start_browser_upload_batch(self, **request):
        return self._uploads.start_browser_upload_batch(**request)

    def get_batch_members(self, batch_id, tab_id=''):
        return {'items': self._transfers.list_batch_members(batch_id, tab_id=tab_id)}

    def finalize_browser_upload_batch(self, **request):
        return self._uploads.finalize_browser_upload_batch(**request)

    def cancel_transfer(self, transfer_id, *, tab_id=''):
        return self._transfers.cancel_operation(str(transfer_id or '').strip(), tab_id=str(tab_id or '').strip(),
                                                connection_lookup=self._connection_lookup)

    def delete_recent_transfer(self, transfer_id, *, tab_id=''):
        if not self._transfers.delete_recent_transfer(transfer_id, tab_id=str(tab_id or '').strip()):
            raise ValueError('transfer not found')
        return {'transfer_id': str(transfer_id or '').strip(), 'deleted': True}

    def clear_recent_transfers(self, *, tab_id='', machine_id=''):
        return {'removed': self._transfers.clear_recent_transfers(tab_id=str(tab_id or '').strip(),
                                                                   machine_id=str(machine_id or '').strip())}

    def get_browser_upload_status(self, transfer_id, *, tab_id):
        return self._uploads.get_browser_upload_status(transfer_id, tab_id=tab_id)

    def update_browser_upload_progress(self, transfer_id, **request):
        return self._uploads.update_browser_upload_progress(transfer_id, **request)

    def fail_browser_upload_transfer(self, transfer_id, error, *, tab_id=''):
        return self._uploads.fail_browser_upload_transfer(transfer_id, error, tab_id=tab_id)
