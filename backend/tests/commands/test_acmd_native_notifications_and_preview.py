import hashlib
import importlib
import json
import sys
import tarfile
import zipfile
from datetime import datetime
from queue import Queue
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.commands.acmd.registry import ArgumentCommandRegistry
from client.commands.runtime.executor import CommandExecutor
from client.commands.runtime.hosts import LinuxCommands, WindowsCommands, iOSCommands
from client.remote_files.manager import RemoteFilesManager
from server.application.command.command_planner import CommandPlanner


notify_module = importlib.import_module('client.commands.acmd.standalone.notify')


def run(host, text):
    payload = CommandPlanner.__new__(CommandPlanner).parse_argument_command(text)
    return ArgumentCommandRegistry(host).execute(payload)


def test_windows_next_command_runs_before_notification_finishes(monkeypatch):
    for name in ('win32api', 'win32con', 'win32event', 'win32gui'):
        monkeypatch.setitem(sys.modules, name, SimpleNamespace())
    queue = Queue()
    monkeypatch.setattr(notify_module, '_windows_notifications', queue)
    monkeypatch.setattr(notify_module, '_windows_worker', None)
    entered = Event()
    release = Event()
    received = []

    def display(*_apis):
        received.append(queue.get(timeout=2))
        entered.set()
        release.wait(timeout=2)
        received.append(queue.get(timeout=2))

    monkeypatch.setattr(notify_module, '_run_windows_notifications', display)
    win = WindowsCommands(None)
    executor = CommandExecutor(None)
    executor.catalog.platform_commands = win
    args = {'title': 'RCH', 'message': 'first'}
    try:
        assert executor.execute_argument_command('notice', {'name': 'notify', 'args': args}) == (1, 'Notification queued.')
        assert entered.wait(timeout=2) and not release.is_set()
        assert executor.execute_command('next-command', 'getpid')[0] == 1
        assert run(win, 'acmd notify --message second') == (1, 'Notification queued.')
        worker = notify_module._windows_worker
        assert worker.daemon and worker.is_alive()
    finally:
        release.set()
        if notify_module._windows_worker:
            notify_module._windows_worker.join(timeout=3)
    assert received == [('RCH', 'first'), ('RCH', 'second')]
    assert not worker.is_alive()


def test_windows_balloon_requests_are_cleaned_up_on_native_callback(monkeypatch):
    pending = Mock()
    pending.get.side_effect = [('title Ω', 'message Ω'), SystemExit]
    monkeypatch.setattr(notify_module, '_windows_notifications', pending)
    wndclass = SimpleNamespace()
    icon_calls = Mock()
    cleanup = Mock()
    constants = SimpleNamespace(WM_APP=32768, WM_USER=1024, IDI_APPLICATION=32512)
    api = SimpleNamespace(GetModuleHandle=lambda _: 2)
    event = SimpleNamespace(QS_ALLINPUT=1, MsgWaitForMultipleObjects=Mock())
    pump = Mock(side_effect=lambda: wndclass.lpfnWndProc[32769](3, 32769, 1, 1028))
    gui = SimpleNamespace(
        WNDCLASS=lambda: wndclass,
        RegisterClass=lambda cls: 51,
        CreateWindowEx=Mock(return_value=3),
        LoadIcon=lambda *_: 4,
        Shell_NotifyIcon=icon_calls,
        DestroyWindow=cleanup,
        PumpWaitingMessages=pump,
        NIF_ICON=2, NIF_MESSAGE=1, NIF_TIP=4, NIF_INFO=16, NIIF_INFO=1,
        NIM_ADD=0, NIM_MODIFY=1, NIM_DELETE=2,
    )
    with pytest.raises(SystemExit):
        notify_module._run_windows_notifications(api, constants, event, gui)
    assert [call.args[0] for call in icon_calls.call_args_list] == [0, 1, 2]
    submitted = icon_calls.call_args_list[1].args[1]
    assert submitted[6] == 'message Ω' and submitted[8] == 'title Ω'
    cleanup.assert_called_once_with(3)
    event.MsgWaitForMultipleObjects.assert_not_called()


def test_python_package_check_has_same_fields_in_both_modes():
    host = LinuxCommands(None)
    for module, importable in [('json', True), ('rch_missing_module_xyz', False)]:
        status, output = run(host, f'acmd python_packages -n {module} --json')
        assert status == 1
        data = json.loads(output)
        assert data['module'] == module and data['importable'] is importable
        assert ('error' in data) is not importable
        assert data['package_dependencies'] == []
        assert bool(data['module_path']) is importable
        assert str(importable) in run(host, f'acmd python_packages -n {module}')[1]


def test_zip_acmd_tree_matches_remote_files_and_tar_keeps_tree(tmp_path):
    host = LinuxCommands(None)
    zip_path = tmp_path / 'demo.zip'
    with zipfile.ZipFile(zip_path, 'w') as archive:
        archive.writestr('x/nested/readme.txt', 'hello')
        archive.writestr('top.txt', 'world')
    status, text = run(host, f'acmd archive_peek "{zip_path}"')
    assert status == 1
    from core.utils.formatting import format_bytes

    archive_size = format_bytes(zip_path.stat().st_size)
    assert text.splitlines() == [f'demo.zip ({archive_size})', '├── x/', '│   └── nested/',
                                 '│       └── readme.txt (5 B)', '└── top.txt (5 B)']
    status, raw = run(host, f'acmd archive_peek "{zip_path}" --json')
    assert status == 1
    preview = json.loads(raw)
    assert preview == {
        'name': 'demo.zip', 'archive_size': archive_size, 'tree': [
            {'name': 'x', 'children': [{'name': 'nested', 'children': [
                {'name': 'readme.txt', 'size': '5 B'},
            ]}]},
            {'name': 'top.txt', 'size': '5 B'},
        ],
    }
    status, browser = RemoteFilesManager().peek_archive(host, {'path': str(zip_path)})
    assert status == 1
    assert browser['entry_count'] == 2 and browser['archive_size'] == zip_path.stat().st_size
    assert browser['tree'][0]['children'][0]['children'][0]['path'] == 'x/nested/readme.txt'
    _, raw = run(host, f'acmd archive_peek "{zip_path}" --limit 1 --json')
    assert json.loads(raw) == {**preview, 'tree': preview['tree'][:1], 'truncated': True}

    source = tmp_path / 'file.txt'
    source.write_text('example')
    tar_path = tmp_path / 'demo.tar.gz'
    with tarfile.open(tar_path, 'w:gz') as archive:
        archive.add(source, 'n/child.txt')
        archive.add(source, 'other.txt')
    status, text = run(host, f'acmd archive_peek "{tar_path}" --limit 1')
    assert status == 1 and '└── n/' in text and 'child.txt (7 B)' in text
    assert 'and more' in text
    status, raw = run(host, f'acmd archive_peek "{tar_path}" --limit 1 --json')
    assert status == 1
    preview = json.loads(raw)
    assert preview['truncated'] is True
    assert preview['tree'] == [{'name': 'n', 'children': [{'name': 'child.txt', 'size': '7 B'}]}]
    assert not (tmp_path / 'n').exists()


def test_ios_shell_runs_moved_file_console_and_device_commands(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('RCH_IOS_QA', 'expanded')
    shell = iOSCommands(None)
    executor = CommandExecutor(None)
    executor.catalog.platform_commands = shell

    def execute(line):
        return executor.execute_command('ios-test', line)

    assert execute('touch demo.txt')[0] == 1
    (tmp_path / 'demo.txt').write_text('hello')
    assert execute('ls')[1] == 'demo.txt'
    assert execute('cat demo.txt') == (1, 'hello')
    assert execute('md5sum demo.txt')[1] == f'{hashlib.md5(b"hello").hexdigest()}  demo.txt'
    assert execute('printenv RCH_IOS_QA') == (1, 'expanded')
    assert execute('echo $RCH_IOS_QA') == (1, 'expanded')

    console = SimpleNamespace(clear=Mock(), set_idle_timer_disabled=Mock())
    speech = SimpleNamespace(say=Mock())
    location = SimpleNamespace(start_updates=Mock(), stop_updates=Mock(), get_location=lambda: {'status': 'mock'})
    due = datetime(2026, 11, 19, 1, 0)
    item = SimpleNamespace(title='Test', due_date=due,
                           alarms=[SimpleNamespace(date=due, location=None, proximity=None)])
    reminders = SimpleNamespace(get_reminders=lambda *, completed: [] if completed else [item])
    for name, module in [('console', console), ('speech', speech),
                         ('location', location), ('reminders', reminders)]:
        monkeypatch.setitem(sys.modules, name, module)
    ios_module = importlib.import_module('client.commands.shell.platform.ios')
    monkeypatch.setattr(ios_module.time, 'sleep', lambda _: None)
    monkeypatch.setattr(ios_module, 'get_ios_contacts', lambda: [{'name': 'Sample'}])
    assert execute('clear_console')[0] == 1
    console.clear.assert_called_once()
    assert execute('speak demo')[0] == 1
    speech.say.assert_called_once_with('demo')
    assert execute('keep_awake off')[0] == 1
    console.set_idle_timer_disabled.assert_called_once_with(False)
    assert execute('get_location') == (1, '{"status": "mock"}')
    location.stop_updates.assert_called_once()
    assert json.loads(execute('list_contacts')[1]) == [{'name': 'Sample'}]
    assert json.loads(execute('list_reminders')[1])[0]['alarms'][0]['date'] == due.isoformat()


def test_python_packages_lists_installations_and_only_snapshot_loaded_modules(monkeypatch):
    packages = importlib.import_module('client.commands.acmd.standalone.python_packages')
    host = LinuxCommands(None)
    distribution = SimpleNamespace(metadata={'Name': 'Example-Tool'}, version='2.1')
    monkeypatch.setitem(sys.modules, 'example_tool', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'example_tool.child', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'blocked_module', None)
    monkeypatch.delitem(sys.modules, 'late_example_module', raising=False)

    def known_packages():
        monkeypatch.setitem(sys.modules, 'late_example_module', SimpleNamespace())
        return {name: ['Example-Tool'] for name in ('example_tool', 'blocked_module', 'late_example_module')}

    monkeypatch.setattr(packages, 'metadata', SimpleNamespace(
        packages_distributions=known_packages, distributions=lambda: [distribution],
    ))
    assert run(host, 'acmd python_packages -l --filter EXAMPLE') == (1, 'example_tool')
    status, text = run(host, 'acmd python_packages --filter EXAMPLE --json')
    assert status == 1 and json.loads(text) == [{'package': 'Example-Tool', 'version': '2.1'}]
    status, text = run(host, 'acmd python_packages --loaded --filter example_tool --json')
    assert status == 1 and json.loads(text) == [{'module': 'example_tool'}]
    assert run(host, 'acmd python_packages -l -n example_tool')[0] == 0
    assert run(host, 'acmd python_packages --name example_tool --filter example')[0] == 0
    assert run(host, 'acmd import_check example_tool')[0] == 0
    assert not hasattr(host, 'piplist')


def test_python_package_name_alias_and_missing_dependency(monkeypatch):
    packages = importlib.import_module('client.commands.acmd.standalone.python_packages')
    host = LinuxCommands(None)
    distribution = SimpleNamespace(metadata={'Name': 'Example-Image'}, version='1.0', requires=['dep'])
    aliases = {'image': ['Example-Image']}
    look_up = Mock(return_value=distribution)

    def import_module(name):
        if name == 'image':
            return SimpleNamespace(__file__='/tmp/image.py', __version__='0.9')
        if name == 'broken':
            raise ModuleNotFoundError("No module named 'dependency'", name='dependency')
        raise ModuleNotFoundError(f"No module named '{name}'", name=name)

    monkeypatch.setattr(packages, 'importlib', SimpleNamespace(import_module=import_module))
    monkeypatch.setattr(packages, 'metadata', SimpleNamespace(
        packages_distributions=lambda: aliases, distribution=look_up,
    ))
    status, text = run(host, 'acmd python_packages -n Example-Image --json')
    assert status == 1 and json.loads(text) == {
        'module': 'image', 'importable': True, 'module_path': '/tmp/image.py',
        'module_version': '0.9', 'package_name': 'Example-Image',
        'package_version': '1.0', 'package_dependencies': ['dep'],
    }
    aliases['example_image'] = ['Example-Image']
    status, text = run(host, 'acmd python_packages -n Example-Image --json')
    assert status == 1
    assert json.loads(text)['error'] == 'Specify a module name: example_image, image'
    look_up.reset_mock()
    status, text = run(host, 'acmd python_packages -n broken --json')
    assert status == 1 and json.loads(text)['error'] == "No module named 'dependency'"
    look_up.assert_not_called()
