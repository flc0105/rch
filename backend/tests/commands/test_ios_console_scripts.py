"""iOS command-to-Script migration: catalog, parameters and SDK behavior."""

import json
import runpy
from datetime import datetime, timezone
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from client.commands.platform.ios import iOSCommands
from client.commands.runtime.request import CommandExecutionRequest
from client.commands.runtime.shell_command_runner import ShellCommandRunner
from client.runtime.sdk import artifact
from core.utils.script_metadata import read_script_metadata_from_file, resolve_script_params


SCRIPTS_ROOT = Path(__file__).resolve().parents[2] / 'server/resources/scripts/ios'


def _run(name, monkeypatch, **kwargs):
    script_path = SCRIPTS_ROOT / 'console' / name
    return runpy.run_path(str(script_path), init_globals={'kwargs': kwargs})


def test_console_script_catalog_and_remote_picker():
    assert not (SCRIPTS_ROOT / 'pythonista').exists()
    assert not (SCRIPTS_ROOT / 'misc/get_reminders.py').exists()
    names = ('close_editor_tabs', 'open_in', 'quick_look', 'openurl', 'pick_upload', 'kill_app')
    for name in names:
        file_path = SCRIPTS_ROOT / 'console' / f'{name}.py'
        meta = read_script_metadata_from_file(str(file_path))
        assert meta['name'] == f'ios/console/{name}'
        assert meta['platforms'] == ['ios']
        assert meta['category'] == 'Console'

    for name in ('open_in', 'quick_look'):
        meta = read_script_metadata_from_file(str(SCRIPTS_ROOT / 'console' / f'{name}.py'))
        assert meta['params'][0]['type'] == 'remote_file'
        assert resolve_script_params(meta, {'file_path': '/tmp/file'}) == {'file_path': '/tmp/file'}
        with pytest.raises(ValueError, match='Missing required'):
            resolve_script_params(meta, {})

    upload_meta = read_script_metadata_from_file(str(SCRIPTS_ROOT / 'console/pick_upload.py'))
    assert next(p for p in upload_meta['params'] if p['name'] == 'file_path')['type'] == 'remote_file'
    assert resolve_script_params(upload_meta, {}) == {'kind': 'photo', 'file_path': ''}

    url_meta = read_script_metadata_from_file(str(SCRIPTS_ROOT / 'console/openurl.py'))
    assert resolve_script_params(url_meta, {'url': 'https://example.com'}) == {'url': 'https://example.com'}


def _make_ios_shell_runner(commands):
    executor = SimpleNamespace(
        command_variable_resolver=SimpleNamespace(resolve=lambda command, **kw: command),
        execute_bound_request=lambda request, invoke: invoke(commands),
    )
    return ShellCommandRunner(executor)


def test_reminder_command_defaults_to_json_with_details(monkeypatch):
    alarm = SimpleNamespace(
        date=datetime(2026, 11, 15, 9, 30, tzinfo=timezone.utc),
        location=('Office', 30.0, 120.0, 100),
        proximity='enter',
    )
    todo = SimpleNamespace(
        title='Todo', notes='Bring notes',
        due_date=datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc),
        completion_date=None, priority=1, url='https://example.org', alarms=[alarm],
    )
    done = SimpleNamespace(
        title='Done', notes='', due_date=None,
        completion_date=datetime(2026, 11, 11, 14, 0),
        priority=0, url=None, alarms=[],
    )
    monkeypatch.setitem(sys.modules, 'reminders', SimpleNamespace(
        get_reminders=lambda *, completed: [done] if completed else [todo]
    ))
    commands = iOSCommands(SimpleNamespace())
    runner = _make_ios_shell_runner(commands)
    status, body = runner.execute(CommandExecutionRequest(command_id=1), 'list_reminders')
    assert status == 1
    assert json.loads(body) == [
        {
            'status': 'Pending', 'title': 'Todo', 'notes': 'Bring notes',
            'dueDate': '2026-11-15T08:00:00+00:00', 'completionDate': None,
            'priority': 1, 'url': 'https://example.org',
            'alarms': [{'date': '2026-11-15T09:30:00+00:00',
                        'location': ['Office', 30.0, 120.0, 100], 'proximity': 'enter'}],
        },
        {
            'status': 'Completed', 'title': 'Done', 'notes': '',
            'dueDate': None, 'completionDate': '2026-11-11T14:00:00',
            'priority': 0, 'url': '', 'alarms': [],
        },
    ]
    assert runner.execute(CommandExecutionRequest(command_id=2), 'list_reminders --json') == (
        0, 'Usage: list_reminders'
    )


def test_reminder_command_optional_fields_and_empty_json(monkeypatch):
    monkeypatch.setitem(sys.modules, 'reminders', SimpleNamespace(
        get_reminders=lambda *, completed: [] if completed else [SimpleNamespace(title='Minimal')]
    ))
    runner = _make_ios_shell_runner(iOSCommands(SimpleNamespace()))
    status, output = runner.execute(CommandExecutionRequest(command_id=3), 'list_reminders')
    assert status == 1
    assert json.loads(output) == [{
        'status': 'Pending', 'title': 'Minimal', 'notes': '',
        'dueDate': None, 'completionDate': None, 'priority': None,
        'url': '', 'alarms': [],
    }]
    monkeypatch.setitem(sys.modules, 'reminders', SimpleNamespace(
        get_reminders=lambda *, completed: []
    ))
    assert runner.execute(CommandExecutionRequest(command_id=4), 'list_reminders') == (1, '[]')


def test_contacts_command_json_only(monkeypatch):
    contacts = [{'full_name': 'Alice', 'phone': [{'label': 'home', 'value': '+123'}]}]
    monkeypatch.setattr('client.commands.platform.utils.ios_util.get_ios_contacts',
                        lambda: contacts)
    commands = iOSCommands(SimpleNamespace())
    runner = _make_ios_shell_runner(commands)
    status, output = runner.execute(CommandExecutionRequest(command_id=5), 'list_contacts')
    assert status == 1 and json.loads(output) == contacts
    assert runner.execute(CommandExecutionRequest(command_id=6), 'list_contacts --json') == (
        0, 'Usage: list_contacts'
    )
    assert commands.list_contacts.__func__.help is not None


def test_reminder_error_is_command_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, 'reminders', SimpleNamespace(
        get_reminders=lambda *, completed: (_ for _ in ()).throw(RuntimeError('permission denied'))
    ))
    status, message = iOSCommands(SimpleNamespace()).list_reminders()
    assert status == 0 and 'permission denied' in message


@pytest.mark.parametrize('script_name,method', [('open_in.py', 'open_in'), ('quick_look.py', 'quicklook')])
def test_remote_file_actions(monkeypatch, tmp_path, capsys, script_name, method):
    seen = []
    monkeypatch.setitem(sys.modules, 'console', SimpleNamespace(**{method: lambda path: seen.append(path)}))
    selected_file = tmp_path / 'chosen.txt'
    selected_file.write_text('content')
    _run(script_name, monkeypatch, file_path=str(selected_file))
    assert seen == [str(selected_file)]
    assert str(selected_file) in capsys.readouterr().out
    with pytest.raises(FileNotFoundError):
        _run(script_name, monkeypatch, file_path=str(tmp_path / 'absent.txt'))


def test_openurl_input(monkeypatch, capsys):
    seen = []
    monkeypatch.setitem(sys.modules, 'webbrowser', SimpleNamespace(open=lambda url: seen.append(url) or True))
    _run('openurl.py', monkeypatch, url='https://example.com')
    assert seen == ['https://example.com']
    assert 'True' in capsys.readouterr().out


def test_upload_remote_file(monkeypatch, tmp_path, capsys):
    picked = tmp_path / 'music.aiff'
    picked.write_bytes(b'aiff')
    called = []
    monkeypatch.setattr(artifact, 'save', lambda path, **options: called.append((path, options)) or {'uploaded': True})
    _run('pick_upload.py', monkeypatch, file_path=str(picked))
    assert called == [(str(picked), {'type': 'saved', 'category': 'downloads'})]
    assert 'True' in capsys.readouterr().out


def test_upload_document_native_picker(monkeypatch, tmp_path):
    chosen = tmp_path / 'document.txt'
    chosen.write_text('data')
    monkeypatch.setitem(sys.modules, 'dialogs', SimpleNamespace(pick_document=lambda: str(chosen)))
    calls = []
    monkeypatch.setattr(artifact, 'save', lambda path, **options: calls.append((path, options)) or {})
    _run('pick_upload.py', monkeypatch, kind='file')
    assert calls == [(str(chosen), {'type': 'saved', 'category': 'downloads'})]


def test_upload_photo_preserves_jpeg_and_removes_temp(monkeypatch):
    saved = []

    class Image:
        mode = 'RGBA'
        def convert(self, mode):
            assert mode == 'RGB'
            self.mode = 'RGB'
            return self
        def save(self, path, **kwargs):
            assert kwargs == {'format': 'JPEG', 'quality': 90}
            Path(path).write_bytes(b'JPEG bytes')

    monkeypatch.setitem(sys.modules, 'photos', SimpleNamespace(pick_image=lambda: Image()))

    def save(path, **options):
        assert Path(path).read_bytes() == b'JPEG bytes'
        assert Path(path).name.startswith('photo_') and path.endswith('.jpg')
        saved.append((path, options))
        return {'artifact_id': 'mock'}

    monkeypatch.setattr(artifact, 'save', save)
    _run('pick_upload.py', monkeypatch, kind='photo')
    assert len(saved) == 1
    assert saved[0][1] == {'type': 'saved', 'category': 'downloads'}
    assert not Path(saved[0][0]).exists()


def test_upload_photo_failure_still_cleans_temporary_file(monkeypatch):
    saved = []

    class Image:
        mode = 'RGB'
        def save(self, path, **kwargs):
            Path(path).write_bytes(b'JPEG bytes')

    monkeypatch.setitem(sys.modules, 'photos', SimpleNamespace(pick_image=lambda: Image()))
    def failed(path, **options):
        saved.append(path)
        raise RuntimeError('server unavailable')
    monkeypatch.setattr(artifact, 'save', failed)
    with pytest.raises(RuntimeError, match='server unavailable'):
        _run('pick_upload.py', monkeypatch)
    assert len(saved) == 1 and not Path(saved[0]).exists()


def test_kill_app_script_retains_forced_exit_behavior(monkeypatch):
    class ExitReached(Exception):
        pass
    monkeypatch.setattr('time.sleep', lambda _: None)
    monkeypatch.setattr('os._exit', lambda code: (_ for _ in ()).throw(ExitReached(code)))
    with pytest.raises(ExitReached, match='0'):
        _run('kill_app.py', monkeypatch)
