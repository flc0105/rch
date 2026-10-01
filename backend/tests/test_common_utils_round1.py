import unittest

from core.platform.normalization import normalize_arch, normalize_platform, normalize_platform_alias, platform_key
from core.utils.formatting import format_bytes, format_bytes_precise, get_size


class CommonUtilityRound1Tests(unittest.TestCase):
    def test_terminal_byte_style_and_legacy_style_can_coexist(self):
        self.assertEqual('1.71 MB', format_bytes(1796001))
        self.assertEqual('188 KB', format_bytes(192512))
        self.assertEqual('1.00MB', get_size(1024 * 1024))

    def test_precise_storage_style_preserves_existing_cleanup_output(self):
        self.assertEqual('512 B', format_bytes_precise(512))
        self.assertEqual('1.5 KB', format_bytes_precise(1536))
        self.assertEqual('1.00 MB', format_bytes_precise(1024 * 1024))

    def test_platform_alias_and_arch_normalization_are_canonical(self):
        self.assertEqual('mac', normalize_platform_alias('Darwin'))
        self.assertEqual('linux', normalize_platform_alias('Ubuntu'))
        self.assertEqual('ios', normalize_platform_alias('iPadOS'))
        self.assertEqual('*', normalize_platform('common'))
        self.assertEqual('amd64', normalize_arch('x86_64'))
        self.assertEqual('amd64', normalize_arch('x64'))
        self.assertEqual('arm64', normalize_arch('aarch64'))
        self.assertEqual('mac-arm64', platform_key('darwin', 'aarch64'))


if __name__ == '__main__':
    unittest.main()
