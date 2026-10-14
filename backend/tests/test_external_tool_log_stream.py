import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile

from core.external_tools.files import read_text_log_chunk
from core.external_tools.meta import normalize_meta
from core.external_tools.payload import client_action_payload
from client.external_tools.daemon_instance import ExternalToolDaemonInstance

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

    def test_payload_keeps_original_action_shape(self):
        opts = {'action': 'logs', 'instance_id': 'i', 'params': {}, 'runtime': {}, 'max_bytes': 100}
        module = {'id': 'mod', 'package_id': 'pkg'}
        original = client_action_payload(module, **opts)
        self.assertNotIn('cursor', original)
        next_one = client_action_payload(module, cursor='1:2:3', **opts)
        self.assertEqual(next_one['cursor'], '1:2:3')

    def test_client_log_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / 'stdout.log'
            path.write_text('line 1\n')
            instance = ExternalToolDaemonInstance.__new__(ExternalToolDaemonInstance)
            runtime = {'stdout': str(path)}
            first = instance.read_logs_payload({'tool_id':'h','runtime':runtime, 'max_bytes': 128})
            self.assertEqual(first['content'], 'line 1\n')
            with path.open('a') as file: file.write('line 2\n')
            second = instance.read_logs_payload({'tool_id':'h','runtime':runtime, 'cursor':first['cursor'], 'max_bytes':128})
            self.assertEqual(second['content'], 'line 2\n')

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
