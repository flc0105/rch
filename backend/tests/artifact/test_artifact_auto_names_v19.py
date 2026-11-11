"""Generated Artifact names and multipart upload wire names."""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.utils.artifact_naming import (
    build_artifact_filename, build_command_name,
)
from client.commands.strategies.http_transfer.cancelable import CancelableMultipartUploadStream
from client.commands.strategies.http_transfer.legacy import LegacyHttpTransferStrategy
from client.commands.common.services.transfer.http_file_transfer_service import CommandHttpFileTransferService
from server.application.artifact.command_output_artifact_service import CommandOutputArtifactService


STAMP = datetime(2026, 11, 10, 18, 32, 18)


@pytest.mark.parametrize('command,expected', [
    ('ps aux', 'ps'),
    ('acmd clipboard get', 'acmd_clipboard'),
    ('shell ps aux', 'shell_ps'),
    ('shell_stream ls -la', 'shell_stream_ls'),
    ('git status', 'git'),
    ('read /etc/hosts', 'read'),
    ('/usr/bin/python3 -V', 'python3'),
    ('"C:\\Program Files\\Tool.exe" -h', 'tool_exe'),
    ('', 'output'),
    ('!!!', 'output'),
    ('verylongcommandname' * 8, 'verylongcommandnameverylongcomma'),
])
def test_build_command_name_uses_generic_first_word(command, expected):
    assert build_command_name(command) == expected


def test_timestamped_names_share_one_contract():
    assert build_artifact_filename('screenshot', '.png', now=STAMP) == 'screenshot_20261110_183218.png'
    assert build_artifact_filename('webcam', 'jpg', now=STAMP) == 'webcam_20261110_183218.jpg'
    assert build_artifact_filename('photo', 'heic', now=STAMP) == 'photo_20261110_183218.heic'


def test_command_script_job_and_terminal_names():
    service = CommandOutputArtifactService(SimpleNamespace())
    assert service.build_output_name(category='command_output', source_command='acmd clipboard get', now=STAMP) == 'command_output_20261110_183218_acmd_clipboard.txt'
    assert service.build_output_name(category='script_output', source_command='tools/trash_items.py', now=STAMP) == 'script_20261110_183218_trash_items.txt'
    assert service.build_output_name(category='job_output', source_command='example_monitor', now=STAMP) == 'job_output_20261110_183218_example_monitor.json'
    assert service.build_output_name(category='command_output', source_command='', now=STAMP, output_name_prefix='terminal_output', output_format='json') == 'terminal_output_20261110_183218.json'
    assert service.build_output_name(category='command_output', source_command='', now=STAMP, output_name_prefix='pty_output') == 'pty_output_20261110_183218.txt'


def test_job_uses_job_name_not_instance_display_name(tmp_path):
    class FakeRegistry:
        def allocate_artifact_path(self, *, original_name, machine_id, artifact_type):
            return dict(file_path=str(tmp_path / original_name), original_name=original_name,
                        stored_name=original_name, machine_id=machine_id)
        def register_existing_artifact(self, **kwargs):
            return kwargs
    service = CommandOutputArtifactService(FakeRegistry())
    service._now = lambda: STAMP
    item = service.save_text_output(
        content='{}', category='job_output', output_format='json',
        hostname='mac', machine_id='machine', source_command='Example Monitor 4a2de06d',
        job_name='example_monitor', job_id='4a2de06d',
    )
    assert item['original_name'] == 'job_output_20261110_183218_example_monitor.json'
    assert item['job_id'] == '4a2de06d'


def test_cancelable_multipart_uses_explicit_name_without_renaming_local_path(tmp_path):
    local = tmp_path / 'screenshot_random_tmp.png'
    local.write_bytes(b'xyz')
    owner = SimpleNamespace(_ensure_not_cancelled=lambda: None)
    stream = CancelableMultipartUploadStream(owner, str(local), {}, chunk_size=4096,
                                            filename='screenshot_20261110_183218.png')
    assert b'filename="screenshot_20261110_183218.png"' in stream._prefix
    assert stream.read() == stream._prefix + b'xyz' + stream._suffix
    assert local.read_bytes() == b'xyz'


def test_legacy_multipart_uses_explicit_name_without_renaming_local_path(tmp_path):
    local = tmp_path / 'webcam_tmp.jpg'
    local.write_bytes(b'xyz')
    owner = SimpleNamespace()
    strategy = LegacyHttpTransferStrategy(owner)
    strategy.configure_context_for_upload = lambda: None
    session = Mock()
    strategy.create_http_session = lambda: session
    strategy.upload_file(str(local), 'https://example.invalid', {}, filename='webcam_20261110_183218.jpg')
    upload = session.post.call_args.kwargs['files']['file']
    assert upload[0] == 'webcam_20261110_183218.jpg'
    assert local.read_bytes() == b'xyz'


def test_command_media_upload_passes_wire_name_and_origin(tmp_path):
    local = tmp_path / 'random_tmp.png'
    local.write_bytes(b'xyz')
    strategy = Mock()
    strategy.get_mode_name.return_value = 'legacy'
    strategy.get_buffer_size.return_value = 4096
    strategy.upload_file.return_value = SimpleNamespace(raise_for_status=lambda: None)
    client_api = SimpleNamespace(build_file_upload_url=lambda: 'https://example.invalid',
                                 try_parse_json=lambda response: {'data': {'original_name': 'screenshot_20261110_183218.png'}})
    owner = SimpleNamespace(socket=SimpleNamespace(client_id='abc'), command_id=None, _send_info=lambda *args: None)
    service = CommandHttpFileTransferService(owner, client_api=client_api)
    service.get_transfer_strategy = lambda: strategy
    service.upload_single_file_to_server_result(str(local), folder='Screenshots',
        upload_name='screenshot_20261110_183218.png', extra={'origin': 'screenshot_command'})
    assert strategy.upload_file.call_args.kwargs['filename'] == 'screenshot_20261110_183218.png'
    assert 'screenshot_command' in strategy.upload_file.call_args.args[2]['extra']
    assert local.read_bytes() == b'xyz'


def test_macos_screenshot_sends_generated_artifact_name(monkeypatch, tmp_path):
    import os
    from client.commands.platform.services.mac import media_service

    local = tmp_path / 'private_random.png'
    transfer = Mock()
    transfer.upload_single_file_to_server_result.return_value = (1, 'OK')
    owner = SimpleNamespace(
        http_file_transfer_service=transfer,
        _send_info=lambda *args: None,
        _send_success=lambda *args: None,
        _run_shell_command=lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(media_service, 'make_client_temp_file',
                        lambda *args, **kwargs: (os.open(local, os.O_CREAT | os.O_RDWR), str(local)))
    monkeypatch.setattr(media_service, 'cleanup_temp_path', lambda path: None)
    media_service.MacMediaService(owner).capture_screenshot()
    options = transfer.upload_single_file_to_server_result.call_args.kwargs
    assert options['folder'] == 'Screenshots'
    assert options['upload_name'].startswith('screenshot_')
    assert options['upload_name'].endswith('.png')
    assert options['extra'] == {'origin': 'screenshot_command'}
    assert transfer.upload_single_file_to_server_result.call_args.args[0] == str(local)


def test_windows_screenshot_uses_wire_name_not_local_temp(monkeypatch, tmp_path):
    import os
    import sys
    from client.commands.platform.services.win import media_service

    local = tmp_path / 'private_random.png'
    transfer = Mock()
    owner = SimpleNamespace(
        http_file_transfer_service=transfer,
        _send_interim_result=lambda *args: None,
        _send_final_result=lambda *args: None,
    )
    class Image:
        def save(self, path):
            Path(path).write_bytes(b'PNG')
    monkeypatch.setitem(sys.modules, 'pyautogui', SimpleNamespace(screenshot=lambda: Image()))
    monkeypatch.setattr(media_service, 'make_client_temp_file',
                        lambda *args, **kwargs: (os.open(local, os.O_CREAT | os.O_RDWR), str(local)))
    monkeypatch.setattr(media_service, 'cleanup_temp_path', lambda path: None)
    media_service.WinMediaService(owner).capture_screenshot()
    options = transfer.upload_single_file_to_server_result.call_args.kwargs
    assert options['folder'] == 'Screenshots'
    assert options['upload_name'].startswith('screenshot_')
    assert options['upload_name'].endswith('.png')
    assert options['extra'] == {'origin': 'screenshot_command'}
    assert transfer.upload_single_file_to_server_result.call_args.args[0] == str(local)


def test_job_upload_can_send_short_artifact_name_and_preserve_local_photo_temp(tmp_path):
    from client.jobs.core.job import Job

    local = tmp_path / 'photo_random_dimension_temp.jpg'
    local.write_bytes(b'jpg')
    class StubJob(Job):
        def run(self):
            pass
    job = object.__new__(StubJob)
    job._build_upload_form_data = lambda *args, **kwargs: {'folder': 'Job Files', 'job_id': 'job-1'}
    calls = []
    class Response:
        ok = True
    class API:
        def upload_file_source(self, file_path, *, filename, form_data, timeout):
            calls.append((file_path, filename, form_data))
            return Response()
        def try_parse_json(self, response):
            return {'data': {'artifact_id': 'A'}}
    job.client_api = API()
    job._report_uploaded_file = lambda info: None
    Job.upload_file_via_http(job, str(local), folder='Job Files',
                             filename='photo_20261110_183218.jpg')
    assert calls == [(str(local), 'photo_20261110_183218.jpg',
                      {'folder': 'Job Files', 'job_id': 'job-1'})]
    assert local.read_bytes() == b'jpg'
