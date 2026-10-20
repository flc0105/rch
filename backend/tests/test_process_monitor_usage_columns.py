"""List snapshots expose actual process usage on the existing monitor channel."""
from unittest.mock import patch

from client.commands.common.services.process.process_service import ProcessService


class FakeProcess:
    def __init__(self, pid, cpu, memory):
        self.pid = pid
        self.cpu = cpu
        self.memory = memory
        self.info = {
            'pid': pid, 'ppid': 1, 'name': 'example', 'username': 'user',
            'status': 'running', 'cpu_percent': cpu, 'memory_percent': memory,
        }

    def cpu_percent(self, interval=None):
        return self.cpu

    def memory_percent(self):
        return self.memory


def test_process_list_percentages_have_a_sample_baseline():
    process = FakeProcess(42, 12.75, 4.61)
    service = ProcessService(None)
    with patch('psutil.process_iter', return_value=iter([process])):
        first = service.list_processes()
    assert first[0]['cpu_percent'] is None
    assert first[0]['memory_percent'] == 4.6
    with patch('psutil.process_iter', return_value=iter([process])):
        second = service.list_processes()
    assert second[0]['cpu_percent'] == 12.8
    assert second[0]['memory_percent'] == 4.6


def test_app_list_usage_reuses_process_baseline_and_ignores_missing_pids():
    process = FakeProcess(99, 20.2, 2.25)
    service = ProcessService(None)
    with patch('psutil.process_iter', return_value=iter([process])):
        first = service._app_usage([99, 101])
    assert first[99] == {'cpu_percent': None, 'memory_percent': 2.2}
    assert 101 not in first
    with patch('psutil.process_iter', return_value=iter([process])):
        second = service._app_usage([99])
    assert second[99] == {'cpu_percent': 20.2, 'memory_percent': 2.2}


def test_macos_app_list_includes_process_usage():
    from types import SimpleNamespace
    process = FakeProcess(99, 8.25, 4.25)
    process.status = lambda: 'running'
    service = ProcessService(None)
    result = SimpleNamespace(stdout='false\t99\tNotes')
    with patch('subprocess.run', return_value=result), \
         patch('psutil.Process', return_value=process), \
         patch('psutil.process_iter', side_effect=lambda: iter([process])):
        first = service.list_macos_app()
        second = service.list_macos_app()
    assert first[0]['name'] == 'Notes'
    assert first[0]['cpu_percent'] is None
    assert second[0]['cpu_percent'] == 8.2
    assert second[0]['memory_percent'] == 4.2


def test_windows_app_list_includes_process_usage():
    import sys
    from types import SimpleNamespace
    process = FakeProcess(42, 16.11, 1.56)
    process.name = lambda: 'Editor'
    process.status = lambda: 'running'
    service = ProcessService(None)
    def enum_windows(callback, windows):
        callback(100, windows)
    win32gui = SimpleNamespace(IsWindowVisible=lambda _hwnd: True, EnumWindows=enum_windows)
    win32process = SimpleNamespace(GetWindowThreadProcessId=lambda _hwnd: (1, 42))
    with patch.dict(sys.modules, {'win32gui': win32gui, 'win32process': win32process}), \
         patch('psutil.Process', return_value=process), \
         patch('psutil.process_iter', side_effect=lambda: iter([process])):
        first = service.list_windows_apps()
        second = service.list_windows_apps()
    assert first[0]['name'] == 'Editor'
    assert first[0]['cpu_percent'] is None
    assert second[0]['cpu_percent'] == 16.1
    assert second[0]['memory_percent'] == 1.6
