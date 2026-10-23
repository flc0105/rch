"""FFmpeg screen recording metadata / existing External Tools lifecycle contract."""
import json
import signal
import unittest
from pathlib import Path

from core.external_tools.meta import normalize_meta
from core.external_tools.processes import signal_name_to_value
from server.application.external_tools.external_tool_catalog_service import ExternalToolCatalogService
from server.application.external_tools.external_tool_runtime_service import ExternalToolRuntimeService


META = Path(__file__).resolve().parents[1] / 'server/resources/external_tools/metas/ffmpeg.json'


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


if __name__ == '__main__':
    unittest.main()
