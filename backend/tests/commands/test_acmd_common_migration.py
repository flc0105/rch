import json
import sqlite3
import subprocess
import sys
import tarfile
import threading
import zipfile
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from client.commands.acmd.registry import ArgumentCommandRegistry
from client.commands.runtime.catalog import CommandCatalog
from client.commands.runtime.hosts import LinuxCommands, MacCommands, WindowsCommands, iOSCommands
from client.runtime.execution.context import CommandCancelledError
from server.application.command.command_planner import CommandPlanner


HOSTS = [MacCommands, WindowsCommands, LinuxCommands, iOSCommands]
COMMON = {'sqlite_query', 'image_info', 'import_check', 'archive_peek', 'find', 'wget'}
IOS_ONLY = {'alert', 'tree', 'head', 'tail'}
LOCAL_UI = {'msgbox', 'notify'}


def make_host(host_type=LinuxCommands):
    return host_type(socket=SimpleNamespace(send_event=Mock()))


def execute(host, text):
    payload = CommandPlanner.__new__(CommandPlanner).parse_argument_command(text)
    return ArgumentCommandRegistry(host).execute(payload)


@pytest.mark.parametrize('host_type', HOSTS)
def test_capabilities(host_type, monkeypatch):
    host = make_host(host_type)
    registry = ArgumentCommandRegistry(host)
    entries = {item['name'] for item in registry.list_command_entries()}
    assert COMMON <= entries
    assert IOS_ONLY & entries == (IOS_ONLY if host.command_platform == 'ios' else set())
    assert LOCAL_UI & entries == (LOCAL_UI if host.command_platform != 'linux' else set())
    catalog = CommandCatalog(host.socket)
    catalog.platform_commands = host
    monkeypatch.setattr(catalog, '_get_platform_name', lambda: host.command_platform)
    names = [item['name'] for item in catalog.get_command_manifest_payload()]
    assert len(names) == len(set(names))
    for command in COMMON | IOS_ONLY | LOCAL_UI:
        assert (f'acmd {command}' in names) == (command in entries)
        assert (execute(host, f'acmd {command} --help')[0] == 1) == (command in entries)

    assert ('launchd' in entries) == (host.command_platform == 'mac')
    assert not any(name in host.__class__.__dict__ for name in ('wget', 'find', 'msgbox', 'notify'))


@pytest.mark.parametrize('host_type', HOSTS)
def test_portable_inspection_and_search(host_type, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    host = make_host(host_type)
    with closing(sqlite3.connect('sample # unicode.db')) as conn:
        conn.executescript('CREATE TABLE items(n); INSERT INTO items VALUES (42);')
    status, output = execute(host, 'acmd sqlite_query --db "sample # unicode.db" --query "SELECT n FROM items" --json')
    assert (status, json.loads(output)) == (1, [{'n': 42}])

    for statement in ("DELETE FROM items", "ATTACH DATABASE 'new.db' AS other", 'PRAGMA query_only=OFF'):
        assert execute(host, f'acmd sqlite_query --db "sample # unicode.db" --query "{statement}"')[0] == 0
    assert not (tmp_path / 'new.db').exists()

    (tmp_path / 'sub').mkdir()
    Image.new('RGB', (2, 3)).save('sub/img_sample.png')
    (tmp_path / 'sub' / 'cover.JPG').write_text('test', encoding='utf-8')
    (tmp_path / 'article.txt').write_text('line1\nline2\nline3\n', encoding='utf-8')
    status, output = execute(host, 'acmd image_info sub/img_sample.png --json')
    assert status == 1 and (json.loads(output)['width'], json.loads(output)['height']) == (2, 3)
    assert 'True' in execute(host, 'acmd import_check json')[1]
    assert 'False' in execute(host, 'acmd import_check rch_nonexistent_sample_x83')[1]

    with zipfile.ZipFile('sample.zip', 'w') as archive:
        archive.write('article.txt', 'article.txt')
    with tarfile.open('sample.tar.gz', 'w:gz') as archive:
        archive.add('article.txt', 'article.txt')
        archive.add('sub/img_sample.png', 'nested/img_sample.png')
    status, output = execute(host, 'acmd archive_peek sample.zip --limit 1')
    assert status == 1 and 'article.txt' in output and '... and more' not in output
    status, output = execute(host, 'acmd archive_peek --path sample.tar.gz --limit 1')
    assert status == 1 and 'article.txt' in output and '... and more' in output
    assert execute(host, 'acmd archive_peek sample.zip --limit 0')[0] == 0
    assert not (tmp_path / 'nested').exists()

    for line, expected in (
        ('acmd find --keyword ARTIC', 'article.txt'),
        ('acmd find . --keyword "*.jpg"', 'cover.JPG'),
        ('acmd find --path sub --keyword "img_*.png"', 'img_sample.png'),
        ('acmd find --keyword article.txt', 'article.txt'),
    ):
        status, output = execute(host, line)
        assert status == 1 and Path(output).name == expected
    assert execute(host, 'acmd find --keyword unmatched') == (1, 'No matches found.')
    assert execute(host, 'acmd find bad-directory --keyword miss')[0] == 0
    assert execute(host, 'acmd find --keyword "  "')[0] == 0

    if host.command_platform == 'ios':
        assert 'img_sample.png' in execute(host, 'acmd tree sub -L 1')[1]
        assert execute(host, 'acmd head article.txt -n 1') == (1, 'line1')
        assert execute(host, 'acmd tail article.txt -n 1') == (1, 'line3')
        assert execute(host, 'acmd tail article.txt -n 0') == (1, '')


@pytest.fixture
def endpoint():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == '/redirect':
                self.send_response(302)
                self.send_header('Location', '/file?token=demo')
                self.end_headers()
                return
            if self.path == '/missing':
                self.send_error(404)
                return
            data = b'a' * 1024
            self.send_response(200)
            if self.path != '/unknown.bin':
                self.send_header('Content-Length', str(len(data) + (8 if self.path == '/truncated' else 0)))
            if self.path.startswith('/file?'):
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''report%20name.bin")
            self.end_headers()
            self.wfile.write(data)

    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}'
        finally:
            server.shutdown()
            thread.join()


def test_wget_real_http_progress_redirect_and_paths(tmp_path, monkeypatch, endpoint):
    monkeypatch.chdir(tmp_path)
    host = make_host()
    status, output = execute(host, f'acmd wget {endpoint}/redirect')
    result = tmp_path / 'report name.bin'
    assert status == 1 and output.splitlines() == ['Downloaded 1 KB', str(result)]
    assert result.read_bytes() == b'a' * 1024
    assert host.socket.send_event.call_args.args[1]['message'] == 'Downloading report name.bin (1 KB)'

    status, output = execute(host, f'acmd wget {endpoint}/unknown.bin -o "out dir/renamed.dat"')
    assert status == 1 and (tmp_path / 'out dir' / 'renamed.dat').stat().st_size == 1024
    assert host.socket.send_event.call_args.args[1]['message'] == 'Downloading renamed.dat'
    status, output = execute(host, f'acmd wget {endpoint}/unknown.bin --output "out dir"')
    assert status == 1 and (tmp_path / 'out dir' / 'unknown.bin').is_file()


def test_wget_http_error_short_read_and_cancellation_leave_target(tmp_path, endpoint, monkeypatch):
    monkeypatch.chdir(tmp_path)
    host = make_host()
    target = tmp_path / 'preserved.bin'
    target.write_bytes(b'previous')
    for path, expected in [('missing', 'HTTP 404'), ('truncated', 'incomplete')]:
        status, output = execute(host, f'acmd wget {endpoint}/{path} -o preserved.bin')
        assert status == 0 and expected in output
        assert target.read_bytes() == b'previous'
        assert not list(tmp_path.glob('.rch-wget-*.part'))

    checkpoint = Mock(side_effect=[None, None, CommandCancelledError('cancelled')])
    monkeypatch.setattr(host, '_checkpoint', checkpoint)
    with pytest.raises(CommandCancelledError):
        execute(host, f'acmd wget {endpoint}/unknown.bin -o preserved.bin')
    assert target.read_bytes() == b'previous'
    assert not list(tmp_path.glob('.rch-wget-*.part'))
    assert execute(host, 'acmd wget file:///sample -o preserved.bin')[0] == 0


def test_native_ui_adapters_receive_arguments_as_data(monkeypatch):
    send = Mock()
    alert = Mock(return_value=1)
    monkeypatch.setitem(sys.modules, 'notification', SimpleNamespace(schedule=send))
    monkeypatch.setitem(sys.modules, 'console', SimpleNamespace(alert=alert))

    ios = make_host(iOSCommands)
    assert execute(ios, 'acmd msgbox --title "Hello there" --message "iOS test"')[0] == 1
    assert execute(ios, 'acmd alert --message "Legacy iOS alert"')[0] == 1
    assert execute(ios, 'acmd notify --title Hello --message "iOS test"')[0] == 1
    alert.assert_any_call('Hello there', 'iOS test', 'OK', hide_cancel_button=True)
    alert.assert_called_with('Alert', 'Legacy iOS alert', 'OK', hide_cancel_button=True)
    send.assert_called_once_with('iOS test', delay=0, title='Hello')

    mac = make_host(MacCommands)
    spawn = Mock()
    monkeypatch.setattr(mac.mac_automation, 'spawn_osascript', spawn)
    run = Mock(return_value=SimpleNamespace(returncode=0, stderr=''))
    monkeypatch.setattr(subprocess, 'run', run)
    for command in ('msgbox', 'notify'):
        assert execute(mac, f'acmd {command} --title Hello --message \'quote " example\'')[0] == 1
    assert '\\"' in spawn.call_args.args[0]
    assert '\\"' in run.call_args.args[0][-1]

    win = make_host(WindowsCommands)
    spawn = Mock()
    monkeypatch.setattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, 'Popen', spawn)
    assert execute(win, 'acmd msgbox --title Hello --message \'quote " example\'')[0] == 1
    assert 'quote " example' not in spawn.call_args.args[0][-1]
    assert spawn.call_args.kwargs['env']['RCH_DIALOG_MESSAGE'] == 'quote " example'
