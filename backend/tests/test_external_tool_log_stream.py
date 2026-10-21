import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile

from core.utils.log_reader import read_text_log_chunk
from core.external_tools.meta import normalize_meta
from client.monitor.manager import DeviceMonitorManager
from core.protocol.monitor import normalize_monitor_channels, normalize_monitor_intervals

ROOT = pathlib.Path(__file__).resolve().parents[1] / 'server' / 'resources' / 'external_tools'


class LogStreamTests(unittest.TestCase):
    def test_incremental_and_no_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / 'stdout.log'
            path.write_bytes('old one\n'.encode())
            initial = read_text_log_chunk(path, 65536)
            self.assertEqual(initial['content'], 'old one\n')
            self.assertFalse(initial['reset'])
            self.assertEqual(read_text_log_chunk(path, 65536, initial['cursor'])['content'], '')
            with path.open('ab') as file:
                file.write('new two\n'.encode())
            delta = read_text_log_chunk(path, 65536, initial['cursor'])
            self.assertEqual(delta['content'], 'new two\n')
            self.assertFalse(delta['reset'])
            self.assertEqual(read_text_log_chunk(path, 65536, delta['cursor'])['content'], '')

    def test_rotation_truncation_and_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / 'stdout.log'
            self.assertEqual(read_text_log_chunk(path, 100, '1:2:3')['reset'], True)
            path.write_text('first' * 100)
            original = read_text_log_chunk(path, 32)
            path.rename(path.with_suffix('.old'))
            path.write_text('new file')
            rotated = read_text_log_chunk(path, 32, original['cursor'])
            self.assertTrue(rotated['reset'])
            self.assertEqual(rotated['content'], 'new file')
            path.write_text('x')
            truncated = read_text_log_chunk(path, 32, rotated['cursor'])
            self.assertTrue(truncated['reset'])
            self.assertEqual(truncated['content'], 'x')

    def test_multibyte_increment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / 'stdout.log'
            path.write_text('')
            snap = read_text_log_chunk(path, 8)
            with path.open('ab') as file:
                file.write('中日文\n'.encode())
            acc = ''
            cursor = snap['cursor']
            for i in range(4):
                chunk = read_text_log_chunk(path, 4, cursor)
                acc += chunk['content']
                cursor = chunk['cursor']
                if not chunk['content']: break
            self.assertEqual(acc, '中日文\n')

    def test_log_file_channel_reads_tail_and_deltas(self):
        self.assertEqual(normalize_monitor_channels(['log_file']), ['log_file'])
        self.assertEqual(normalize_monitor_intervals({}, ['log_file'])['log_file'], 0.25)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / 'stdout.log'
            path.write_text('first\n')
            manager = DeviceMonitorManager.__new__(DeviceMonitorManager)
            item = {
                'options': {'path': str(path)},
                'log_cursor': '', 'log_path': '', 'log_seen': False,
            }
            first = manager._collect_log_file(item)
            self.assertEqual(first['content'], 'first\n')
            self.assertTrue(first['exists'])
            self.assertIsNone(manager._collect_log_file(item))
            with path.open('a') as handle:
                handle.write('second\n')
            added = manager._collect_log_file(item)
            self.assertEqual(added['content'], 'second\n')
            self.assertFalse(added['reset'])
            path.rename(path.with_suffix('.old'))
            path.write_text('replacement\n')
            replaced = manager._collect_log_file(item)
            self.assertTrue(replaced['reset'])
            self.assertEqual(replaced['content'], 'replacement\n')
            path.unlink()
            missing = manager._collect_log_file(item)
            self.assertFalse(missing['exists'])
            self.assertTrue(missing['reset'])

    def test_log_file_requires_absolute_remote_path(self):
        manager = DeviceMonitorManager.__new__(DeviceMonitorManager)
        with self.assertRaises(ValueError):
            manager._collect_log_file({
                'options': {'path': 'relative.log'},
                'log_cursor': '', 'log_path': '', 'log_seen': False,
            })

    def test_bundle_meta_and_process(self):
        meta = json.loads((ROOT / 'metas' / 'python-heartbeat-log.json').read_text())
        normalized = normalize_meta(meta)
        self.assertEqual(normalized['modules'][0]['execution'], 'daemon')
        package = ROOT / 'packages' / 'python-heartbeat-log-v1.0.0-common-all.zip'
        with zipfile.ZipFile(package) as zipobj:
            self.assertIsNone(zipobj.testzip())
            with tempfile.TemporaryDirectory() as tmp:
                zipobj.extractall(tmp)
                proc = subprocess.Popen([sys.executable,'-u',str(pathlib.Path(tmp)/'heartbeat.py'),'--interval','0.2'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    lines = [proc.stdout.readline().strip() for _ in range(3)]
                    self.assertIn('started',lines[0])
                    self.assertIn('heartbeat #1',lines[1])
                    self.assertIn('heartbeat #2',lines[2])
                finally:
                    proc.terminate()
                    proc.communicate(timeout=5)

if __name__ == '__main__': unittest.main()
