"""Default names: only namespace prefixes receive two words; raw script/job ids."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.utils.artifact_naming import build_command_name, build_artifact_filename, COMMAND_NAME_TWO_WORD_PREFIXES
from server.application.artifact.command_output_artifact_service import CommandOutputArtifactService
from client.clipboard.manager import ClipboardManager

STAMP = datetime(2026, 11, 10, 18, 32, 18)


def test_two_word_prefixes_are_centralized_not_subcommand_whitelist():
    assert COMMAND_NAME_TWO_WORD_PREFIXES == {'shell', 'shell_stream', 'acmd'}
    for command, label in [
        ('shell ps aux', 'shell_ps'),
        ('shell_stream ls -la', 'shell_stream_ls'),
        ('acmd clipboard get', 'acmd_clipboard'),
        ('acmd whatever-custom-handler run', 'acmd_whatever_custom_handler'),
        ('git status', 'git'),
        ('python3 /tmp/app.py', 'python3'),
        ('acmd --help', 'acmd'),
        ('', 'output'),
    ]:
        assert build_command_name(command) == label


def test_script_path_and_job_key_define_names_without_display_name_fallback(tmp_path):
    class Registry:
        def allocate_artifact_path(self, **kw):
            name = kw['original_name']
            return dict(file_path=str(tmp_path / name), original_name=name,
                        stored_name=name, machine_id='m')
        def register_existing_artifact(self, **kw):
            return kw

    service = CommandOutputArtifactService(Registry())
    service._now = lambda: STAMP
    data = service.save_text_output(
        content='ok', output_kind='script', hostname='host', machine_id='m',
        source_command='script exec tools/trash_items.py',
        extra={'saved_from': 'terminal_output', 'script_path': 'tools/trash_items.py'},
    )
    assert data['original_name'] == 'script_20261110_183218_trash_items.txt'
    with pytest.raises(ValueError, match='script_path is required'):
        service.save_text_output(
            content='ok', output_kind='script', hostname='host', machine_id='m',
            source_command='[Run Script] Pretty Name',
            extra={'saved_from': 'terminal_json_viewer'},
        )
    job = service.save_text_output(
        content='{}', output_kind='job', hostname='host', machine_id='m',
        job_key='clipboard_monitor', output_format='json',
        extra={'saved_from': 'background_job_detail'},
    )
    assert job['original_name'] == 'job_output_20261110_183218_clipboard_monitor.json'


def test_clipboard_raw_image_uses_timestamp_and_file_name_is_unmodified(monkeypatch):
    owner = ClipboardManager.__new__(ClipboardManager)
    uploaded = {}
    def upload(data, *, filename, category, extra):
        uploaded.update(filename=filename, category=category, extra=extra)
        return dict(original_name=filename)
    owner._upload_bytes_artifact = upload
    result = owner._materialize_snapshot({'kind': 'image', 'data': b'png', 'format': 'png'})
    assert result['kind'] == 'image'
    assert uploaded['filename'].startswith('clipboard_') and uploaded['filename'].endswith('.png')
    assert len(uploaded['filename']) == len('clipboard_YYYYMMDD_HHMMSS.png')
    assert uploaded['category'] == 'clipboard'
    assert uploaded['extra'] == {'saved_from': 'clipboard'}
    assert build_artifact_filename('clipboard', 'png', now=STAMP) == 'clipboard_20261110_183218.png'
