import hashlib
import os
import sys
import unittest
from unittest.mock import patch

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from core.device.local_identity import clear_local_identity_cache, get_local_identity
from core.device.machine_identity import build_machine_identity_payload
from core.platform.platform_identity import PlatformInfo


class LocalIdentityRound3Tests(unittest.TestCase):
    def tearDown(self):
        clear_local_identity_cache()

    @staticmethod
    def _raw_components():
        return {
            'hostname': 'test-host',
            'os_name': 'macOS',
            'os_version': '15.7.1',
            'arch': 'x86_64',
            'manufacturer': 'Apple',
            'model': 'MacBookPro18,1',
            'native_id': 'ABC-123',
        }

    def test_get_local_identity_caches_probe_and_normalizes_arch(self):
        raw = self._raw_components()
        platform_info = PlatformInfo(alias='mac', display_name='macOS', system_name='Darwin')

        with patch('core.device.local_identity.detect_platform_info', return_value=platform_info) as detect_platform, \
                patch('core.device.local_identity.detect_machine_identity_components', return_value=raw) as detect_machine, \
                patch('core.device.local_identity.platform.platform', return_value='macOS-15.7.1-x86_64'):
            first = get_local_identity(refresh=True)
            second = get_local_identity()

        self.assertIs(first, second)
        self.assertEqual(1, detect_platform.call_count)
        self.assertEqual(1, detect_machine.call_count)
        self.assertEqual('mac', first.os_alias)
        self.assertEqual('macOS', first.os_type)
        self.assertEqual('amd64', first.arch)
        self.assertEqual('test-host', first.hostname)

        expected_payload = build_machine_identity_payload(raw_components=raw)
        self.assertEqual(expected_payload['machine_id_hash'], first.machine_id)
        self.assertEqual(expected_payload['fingerprint_basis'], first.fingerprint_basis)

    def test_refresh_reprobes_identity(self):
        raw = self._raw_components()
        platform_info = PlatformInfo(alias='mac', display_name='macOS', system_name='Darwin')

        with patch('core.device.local_identity.detect_platform_info', return_value=platform_info) as detect_platform, \
                patch('core.device.local_identity.detect_machine_identity_components', return_value=raw) as detect_machine, \
                patch('core.device.local_identity.platform.platform', return_value='macOS-test'):
            get_local_identity(refresh=True)
            get_local_identity(refresh=True)

        self.assertEqual(2, detect_platform.call_count)
        self.assertEqual(2, detect_machine.call_count)

    def test_client_info_builder_consumes_one_local_identity_snapshot(self):
        from types import SimpleNamespace
        from client.runtime.client_info_builder import ClientInfoBuilder

        identity = SimpleNamespace(
            os_alias='mac',
            os_type='macOS',
            os_full='macOS-test',
            os_name='macOS',
            os_version='15.7.1',
            arch='arm64',
            manufacturer='Apple',
            model='MacBookAir',
            hostname='test-host',
            machine_id='a' * 64,
            fingerprint_basis='basis',
        )
        builder = ClientInfoBuilder('client-1')

        with patch('client.runtime.client_info_builder.get_local_identity', return_value=identity) as get_identity, \
                patch.object(builder, '_build_process_info', return_value={'username': 'u', 'process_name': 'p'}), \
                patch('client.runtime.client_info_builder._get_client_revision_manifest', return_value={'revision': '', 'parts': {}, 'files': {}}), \
                patch('client.runtime.client_info_builder.check_privilege', return_value='user'), \
                patch('client.runtime.client_info_builder.get_executable_path', return_value='python rchclient.py'), \
                patch('client.runtime.client_info_builder.get_system_paths', return_value={}):
            info = builder.build()

        self.assertEqual(1, get_identity.call_count)
        self.assertEqual('mac', info['os_alias'])
        self.assertEqual('macOS', info['os_type'])
        self.assertEqual('arm64', info['arch'])
        self.assertEqual('a' * 64, info['machine_id'])


    def test_machine_payload_from_raw_does_not_probe_again(self):
        raw = self._raw_components()
        with patch('core.device.machine_identity.detect_machine_identity_components', side_effect=AssertionError('unexpected probe')):
            payload = build_machine_identity_payload(raw_components=raw)

        expected_basis = (
            'v1|hostname=test-host|os_name=macos|os_version=15.7.1|arch=x86_64'
            '|manufacturer=apple|model=macbookpro18_1|native_id=abc-123'
        )
        self.assertEqual(expected_basis, payload['fingerprint_basis'])
        self.assertEqual(hashlib.sha256(expected_basis.encode('utf-8')).hexdigest(), payload['machine_id_hash'])


if __name__ == '__main__':
    unittest.main()
