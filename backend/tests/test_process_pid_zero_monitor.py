"""Process monitor permits the valid PID 0 without accepting absent/negative PIDs."""
import unittest
from unittest.mock import Mock

from client.monitor.manager import DeviceMonitorManager


class ProcessPidZeroMonitorTests(unittest.TestCase):
    def setUp(self):
        self.manager = DeviceMonitorManager.__new__(DeviceMonitorManager)
        self.manager._process_service = Mock()
        self.manager._process_service.get_process_basic_detail.return_value = {'pid': 0}

    def test_zero_pid_supported_in_all_detail_channels(self):
        item = {'options': {'pid': 0}}
        fake_process = object()
        psutil = Mock()
        psutil.Process.return_value = fake_process
        self.assertEqual(self.manager._collect_process_detail(psutil, item)['pid'], 0)
        self.assertEqual(self.manager._collect_process_connections(psutil, item)['pid'], 0)
        self.assertEqual(self.manager._collect_process_open_files(psutil, item)['pid'], 0)
        psutil.Process.assert_called_once_with(0)

    def test_negative_or_missing_pid_rejected(self):
        for options in ({'pid': -1}, {}, {'pid': None}, {'pid': ''}, {'pid': 'broken'}, {'pid': 1.5}):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    self.manager._resolve_process_pid({'options': options})
