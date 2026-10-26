"""Focused behavior tests for project module: external_tools."""

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
import signal
from pathlib import Path
from core.external_tools.processes import signal_name_to_value
from client.external_tools.daemon_instance import ExternalToolDaemonInstance
from server.application.external_tools.external_tool_catalog_service import ExternalToolCatalogService
from server.application.external_tools.external_tool_runtime_service import ExternalToolRuntimeService


ROOT = pathlib.Path(__file__).resolve().parents[2] / 'server' / 'resources' / 'external_tools'


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


META = Path(__file__).resolve().parents[2] / 'server/resources/external_tools/metas/ffmpeg.json'


class FFmpegScreenRecordMetaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = normalize_meta(json.loads(META.read_text(encoding='utf-8')))
        cls.modules = {module['id']: module for module in cls.package['modules']}
        catalog = ExternalToolCatalogService(str(META.parent), str(META.parent.parent / 'packages'))
        cls.builder = ExternalToolRuntimeService(catalog, command_execution_api=None).payload_builder
        cls.module = catalog.get_tool('ffmpeg.screen-record')

    def payload(self, platform, arch='amd64', instance_name='recording-test', output_filename='recording.mp4'):
        return self.builder.build_client_start_payload(
            self.module,
            params={'instance_name': instance_name, 'output_filename': output_filename},
            platform_alias=platform,
            arch=arch,
        )

    def test_existing_modules_are_still_available(self):
        self.assertEqual(set(self.modules), {'version', 'screen-push', 'screen-record'})
        self.assertEqual(self.modules['version']['execution'], 'oneshot')
        self.assertEqual(self.modules['screen-push']['execution'], 'daemon')
        self.assertEqual(self.modules['screen-record']['execution'], 'daemon')

    def test_platform_specific_capture_commands(self):
        for platform, arch, capture in (
            ('mac', 'amd64', 'avfoundation'),
            ('mac', 'arm64', 'avfoundation'),
            ('win', 'amd64', 'gdigrab'),
        ):
            with self.subTest(platform=platform, arch=arch):
                payload = self.payload(platform, arch)
                argv = payload['runtime']['argv']
                self.assertEqual(argv[argv.index('-f') + 1], capture)
                self.assertIn('-nostdin', argv)
                self.assertIn('-n', argv)
                self.assertNotIn('-t', argv)  # Manual stop, no preset duration.
                self.assertIn('frag_keyframe', argv[argv.index('-movflags') + 1])
                self.assertEqual(argv[argv.index('-frag_duration') + 1], '1000000')
                self.assertEqual(argv[argv.index('-flush_packets') + 1], '1')
                self.assertTrue(argv[-1].endswith('/ffmpeg/screen-record/instances/recording-test/recording.mp4'))
                self.assertIn('screen-record', payload['tool_id'])
                self.assertEqual(payload['lifecycle']['stop']['signal'], 'INT')

    def test_instance_isolation_and_parameters(self):
        one = self.payload('win', instance_name='capture-one')['runtime']['argv']
        two = self.payload('win', instance_name='capture-two')['runtime']['argv']
        self.assertNotEqual(one[-1], two[-1])
        self.assertIn('/capture-one/recording.mp4', one[-1])
        self.assertIn('/capture-two/recording.mp4', two[-1])

    def test_output_filename_can_change_without_replacing_instance(self):
        first = self.payload('mac', output_filename='recording-01.mp4')
        second = self.payload('mac', output_filename='recording-02.mp4')
        self.assertEqual(first['instance_id'], second['instance_id'])
        self.assertTrue(first['runtime']['argv'][-1].endswith('/recording-test/recording-01.mp4'))
        self.assertTrue(second['runtime']['argv'][-1].endswith('/recording-test/recording-02.mp4'))
        self.assertIn('-n', first['runtime']['argv'])
        self.assertEqual(first['params']['output_filename'], 'recording-01.mp4')

    def test_mac_avfoundation_pixel_format_and_encoded_fps(self):
        argv = self.payload('mac')['runtime']['argv']
        pixel = argv.index('-pixel_format')
        self.assertEqual(argv[pixel + 1], 'nv12')
        self.assertLess(pixel, argv.index('-i'))
        self.assertEqual(argv[argv.index('-framerate') + 1], '12')
        self.assertEqual(argv[argv.index('-vf') + 1], 'fps=12,scale=1280:-2,format=yuv420p')
        self.assertEqual(argv[argv.index('-r') + 1], '12')
        self.assertGreater(argv.index('-r'), argv.index('-i'))

    def test_windows_capture_parameters_not_changed(self):
        argv = self.payload('win')['runtime']['argv']
        self.assertNotIn('-pixel_format', argv)
        self.assertNotIn('-r', argv)
        self.assertEqual(argv[argv.index('-vf') + 1], 'scale=1280:-2,format=yuv420p')

    def test_rch_timestamp_is_not_interpolated_as_external_tool_parameter(self):
        argv = self.payload('mac', output_filename='${rch:timestamp}.mp4')['runtime']['argv']
        self.assertTrue(argv[-1].endswith('/${rch:timestamp}.mp4'))

    def test_manual_stop_signal_is_supported_by_existing_posix_lifecycle(self):
        self.assertEqual(signal_name_to_value('INT'), signal.SIGINT)
        self.assertTrue(self.module['lifecycle']['stop']['kill_after_timeout'])
        self.assertEqual(self.module['lifecycle']['stop']['timeout_sec'], 15)

class ExternalToolDaemonStatusTests(unittest.TestCase):
    def _payload(self, root):
        return {
            'tool_id': 'test-daemon',
            'instance_id': 'default',
            'runtime': {
                'pid_file': str(root / 'tool.pid'),
                'state_file': str(root / 'state.json'),
                'stdout': str(root / 'stdout.log'),
            },
        }

    def test_dead_valid_pid_is_reclaimed_as_stopped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = self._payload(root)
            (root / 'tool.pid').write_text('43210', encoding='utf-8')
            (root / 'state.json').write_text(json.dumps({
                'tool_id': 'test-daemon',
                'instance_id': 'default',
                'last_status': 'running',
            }), encoding='utf-8')

            daemon = ExternalToolDaemonInstance()
            daemon.is_pid_alive = lambda pid: False

            status = daemon.status_from_payload(payload)

            self.assertEqual(status['status'], 'stopped')
            self.assertFalse(status['running'])
            self.assertIsNone(status['pid'])
            self.assertFalse((root / 'tool.pid').exists())
            state = json.loads((root / 'state.json').read_text(encoding='utf-8'))
            self.assertEqual(state['last_status'], 'stopped')
            self.assertTrue(state['stopped_at'])
            self.assertNotIn('stop_result', state)

    def test_malformed_pid_file_remains_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = self._payload(root)
            (root / 'tool.pid').write_text('not-a-pid', encoding='utf-8')
            (root / 'state.json').write_text(json.dumps({
                'tool_id': 'test-daemon',
                'instance_id': 'default',
                'last_status': 'running',
            }), encoding='utf-8')

            daemon = ExternalToolDaemonInstance()
            status = daemon.status_from_payload(payload)

            self.assertEqual(status['status'], 'stale')
            self.assertFalse(status['running'])
            self.assertIsNone(status['pid'])
            self.assertTrue((root / 'tool.pid').exists())
            state = json.loads((root / 'state.json').read_text(encoding='utf-8'))
            self.assertEqual(state['last_status'], 'running')

