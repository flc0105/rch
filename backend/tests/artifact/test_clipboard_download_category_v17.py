from types import SimpleNamespace
from server.application.artifact.remote_file_service import WebRemoteFileService


class TransferStub:
    activity_recorder = None
    def create_transfer(self, **kwargs):
        return {'transfer_id': 't-1', 'filename': kwargs['filename']}
    def get_transfer(self, transfer_id):
        return None


def make_service():
    session = SimpleNamespace(session_info=SimpleNamespace(hostname='test-device'))
    service = WebRemoteFileService(SimpleNamespace(get_connection=lambda client_id: session), None, TransferStub())
    sends = []
    service._start_client_transfer = lambda session, tid, kind, payload: sends.append((kind, payload))
    service._wait_for_transfer_artifact = lambda transfer_id: ({}, {'artifact_id': 'a1'})
    return service, sends


def test_clipboard_download_single_and_zip_uses_clipboard_source():
    service, sends = make_service()
    service.download_file('c1', '/tmp/a.txt', feature='clipboard')
    service.download_paths_as_zip('c1', ['/tmp/a.txt', '/tmp/b.txt'], feature='clipboard')
    assert sends[0][1]['folder'] == 'Clipboard'
    assert sends[1][1]['folder'] == 'Clipboard'


def test_remote_files_download_stays_in_downloads():
    service, sends = make_service()
    service.download_file('c1', '/tmp/a.txt', feature='remote_files')
    service.download_paths_as_zip('c1', ['/tmp/a.txt'], feature='remote_files')
    assert sends[0][1]['folder'] == 'Downloads'
    assert sends[1][1]['folder'] == 'Downloads'
