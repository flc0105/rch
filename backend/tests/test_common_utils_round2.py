import os
import tempfile
import unittest

from client.config.runtime_config_utils import format_runtime_config_value
from core.protocol.monitor import (
    MONITOR_DEFAULT_CHANNELS,
    normalize_monitor_channels,
    normalize_monitor_intervals,
    normalize_monitor_options,
)
from core.protocol.screen import normalize_screen_fps, normalize_screen_quality
from core.protocol.structured_arg_codec import (
    JSON_PREFIX,
    StructuredArgCodec,
    decode_structured_arg,
    encode_structured_arg,
)
from core.utils.datetime_utils import parse_iso_datetime
from core.utils.filesystem import safe_file_size
from core.utils.json_utils import (
    clone_json_value,
    compact_json_dumps,
    json_dumps_or_default,
    json_loads_dict,
    json_loads_or_default,
    json_loads_typed,
)
from core.utils.network import normalize_mac_address
from core.utils.timeouts import normalize_positive_timeout
from server.application.history.history_record_policy import CommandHistoryRecordPolicy


class CommonUtilityRound2Tests(unittest.TestCase):
    def test_structured_arg_codec_is_shared_and_round_trips_unicode(self):
        payload = {'path': '/tmp/你好.txt', 'items': [1, 2, 3]}
        encoded = encode_structured_arg(payload)

        self.assertTrue(encoded.startswith(JSON_PREFIX))
        self.assertEqual(payload, decode_structured_arg(encoded, require_prefix=True))
        self.assertEqual(payload, StructuredArgCodec().decode(f'"{encoded}"'))
        self.assertEqual(JSON_PREFIX, CommandHistoryRecordPolicy.JSON_PAYLOAD_PREFIX)

    def test_structured_arg_codec_can_leave_plain_text_untouched(self):
        self.assertEqual('plain text', decode_structured_arg('plain text'))
        with self.assertRaises(ValueError):
            decode_structured_arg('plain text', require_prefix=True)

    def test_mac_address_normalization_matches_existing_semantics(self):
        self.assertEqual('aa:bb:cc:dd:ee:ff', normalize_mac_address('AA-BB-CC-DD-EE-FF'))
        self.assertEqual('aa:bb:cc:dd:ee:ff', normalize_mac_address('aabbccddeeff'))
        self.assertEqual('0a:0b:0c:0d:0e:0f', normalize_mac_address('a:b:c:d:e:f'))
        self.assertEqual('', normalize_mac_address('00:00:00:00:00:00'))
        self.assertEqual('', normalize_mac_address('not-a-mac'))

    def test_monitor_normalization_is_shared_protocol_behavior(self):
        self.assertEqual(
            ['system', 'network'],
            normalize_monitor_channels(['SYSTEM', 'network', 'network', 'unknown']),
        )
        self.assertEqual(list(MONITOR_DEFAULT_CHANNELS), normalize_monitor_channels(None))
        intervals = normalize_monitor_intervals(
            {'system': 0.01, 'network': 99, 'storage': 'bad'},
            ['system', 'network', 'storage'],
        )
        self.assertEqual(0.25, intervals['system'])
        self.assertEqual(60.0, intervals['network'])
        self.assertEqual(5.0, intervals['storage'])
        self.assertEqual({'pid': 123}, normalize_monitor_options({'pid': 123}))
        self.assertEqual({}, normalize_monitor_options('bad'))

    def test_json_helpers_preserve_typed_store_semantics(self):
        self.assertEqual('{"name":"你好"}', compact_json_dumps({'name': '你好'}))
        self.assertEqual({'a': 1}, json_loads_dict('{"a":1}'))
        self.assertEqual({}, json_loads_dict('[1,2]'))
        self.assertEqual([], json_loads_typed('{"a":1}', []))
        self.assertEqual(['a'], json_loads_typed('["a"]', []))
        original = {'nested': {'items': [1]}}
        cloned = clone_json_value(original)
        self.assertEqual(original, cloned)
        self.assertIsNot(original, cloned)
        self.assertIsNot(original['nested'], cloned['nested'])
        self.assertEqual({'a': 1}, json_loads_or_default('{"a":1}', {}))
        self.assertEqual([], json_loads_or_default('not-json', []))
        self.assertEqual('{}', json_dumps_or_default({'bad': {1}}, default='{}'))

    def test_small_shared_normalizers_keep_previous_behavior(self):
        self.assertIsNone(normalize_positive_timeout(None))
        self.assertIsNone(normalize_positive_timeout(0))
        self.assertEqual(2.5, normalize_positive_timeout('2.5'))
        self.assertIsNotNone(parse_iso_datetime('2026-10-01T12:34:56'))
        self.assertIsNone(parse_iso_datetime('not-a-date'))
        self.assertEqual(15, normalize_screen_fps('bad'))
        self.assertEqual(1, normalize_screen_fps(0))
        self.assertEqual(30, normalize_screen_fps(99))
        self.assertEqual(60, normalize_screen_quality('bad'))
        self.assertEqual(20, normalize_screen_quality(1))
        self.assertEqual(95, normalize_screen_quality(100))

    def test_safe_file_size_and_runtime_config_formatter(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, 'data.bin')
            with open(path, 'wb') as file_obj:
                file_obj.write(b'12345')
            self.assertEqual(5, safe_file_size(path))
            self.assertEqual(0, safe_file_size(os.path.join(tmp_dir, 'missing')))

        self.assertEqual("'hello'", format_runtime_config_value('hello'))
        self.assertEqual('True', format_runtime_config_value(True))
        self.assertEqual('None', format_runtime_config_value(None))
        self.assertEqual('123', format_runtime_config_value(123))


if __name__ == '__main__':
    unittest.main()
