"""Media producers must use Saved category and name uploads after actual bytes."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from client.commands.platform.services.mac import media_service as mac_media
from client.http.client_api import ClientApiClient, ClientApiError
from client.jobs.core.job import Job


def _mac_webcam(monkeypatch, tmp_path, *, capture_status=0, upload_status=1):
    temp_path = tmp_path / 'private_webcam_temp.jpg'
    cleaned = []
    transfer = Mock()
    transfer.upload_single_file_to_server_result.return_value = (upload_status, 'Upload rejected')
    owner = SimpleNamespace(
        http_file_transfer_service=transfer,
        _send_info=lambda *args: None,
    )

    def make_temp(*args, **kwargs):
        assert kwargs['suffix'] == '.jpg'
        return os.open(temp_path, os.O_CREAT | os.O_RDWR), str(temp_path)

    def fake_run(command, **kwargs):
        if command[0] == 'which':
            return SimpleNamespace(returncode=0)
        assert command[:3] == ['imagesnap', '-w', '1']
        assert command[3] == str(temp_path)
        if capture_status == 0:
            temp_path.write_bytes(b'\xff\xd8\xff\xdbmockjpeg')
        return SimpleNamespace(returncode=capture_status)

    monkeypatch.setattr(mac_media, 'make_client_temp_file', make_temp)
    monkeypatch.setattr(mac_media, 'cleanup_temp_path', lambda path: cleaned.append(path))
    monkeypatch.setattr(mac_media.subprocess, 'run', fake_run)

    return mac_media.MacMediaService(owner), transfer, cleaned, str(temp_path)


def test_macos_webcam_upload_uses_canonical_category_and_jpeg_name(monkeypatch, tmp_path):
    service, transfer, cleaned, temp_path = _mac_webcam(monkeypatch, tmp_path)
    status, message = service.capture_webcam_photo()
    assert status == 1 and 'Webcam photo captured' in message
    call = transfer.upload_single_file_to_server_result.call_args
    assert call.args == (temp_path,)
    assert call.kwargs['category'] == 'webcam'
    assert 'folder' not in call.kwargs
    assert call.kwargs['upload_name'].startswith('webcam_')
    assert call.kwargs['upload_name'].endswith('.jpg')
    assert call.kwargs['extra'] == {'saved_from': 'client_command', 'source_command': 'webcam_snap'}
    assert cleaned == [temp_path]


@pytest.mark.parametrize('capture_status,upload_status,expected_message', [
    (1, 1, 'Failed to capture webcam photo'),
    (0, 0, 'Webcam upload failed'),
])
def test_macos_webcam_failed_capture_or_upload_is_failure(
    monkeypatch, tmp_path, capture_status, upload_status, expected_message
):
    service, transfer, cleaned, temp_path = _mac_webcam(
        monkeypatch, tmp_path, capture_status=capture_status, upload_status=upload_status
    )
    status, message = service.capture_webcam_photo()
    assert status == 0 and expected_message in message
    assert transfer.upload_single_file_to_server_result.called == (capture_status == 0)
    assert cleaned == [temp_path]


@pytest.mark.parametrize('status_code,api_code,expected_error', [
    (500, 1, 'Upload rejected'),
    (200, 7, 'Upload rejected'),
])
def test_job_upload_rejects_http_or_api_error_before_reporting(
    tmp_path, status_code, api_code, expected_error
):
    file_path = tmp_path / 'screenshot.png'
    file_path.write_bytes(b'\x89PNG\r\n\x1a\n')

    class FakeApi(ClientApiClient):
        def upload_file(self, path, form_data, *, timeout):
            assert form_data['category'] == 'screenshots'
            response = requests.Response()
            response.status_code = status_code
            response._content = (
                b'{"code": 7, "message": "Upload rejected"}'
                if api_code else b'{"code": 0, "data": {"artifact_id": "id"}}'
            )
            return response

    class PhotoJob(Job):
        def run(self):
            pass

    job = PhotoJob()
    job.client_api = FakeApi()
    reported = []
    job._report_uploaded_file = lambda data: reported.append(data)
    with pytest.raises(ClientApiError, match=expected_error):
        job.upload_file_via_http(str(file_path), category='screenshots')
    assert reported == []


def test_job_upload_reports_success_only_after_api_accepts(tmp_path):
    file_path = tmp_path / 'photo.jpg'
    file_path.write_bytes(b'\xff\xd8jpeg')

    class FakeApi(ClientApiClient):
        def upload_file(self, path, form_data, *, timeout):
            assert form_data['category'] == 'job_files'
            response = requests.Response()
            response.status_code = 200
            response._content = b'{"code": 0, "data": {"artifact_id": "id-1"}}'
            return response

    class PhotoJob(Job):
        def run(self):
            pass

    job = PhotoJob()
    job.client_api = FakeApi()
    reported = []
    job._report_uploaded_file = lambda data: reported.append(data)
    response = job.upload_file_via_http(str(file_path))
    assert response.ok
    assert reported == [{'artifact_id': 'id-1'}]
