"""Small reversible login mask: HTTP is permitted, transport is not confidential."""

import base64
import unittest

from server.web.password_mask import decode_masked_password


KEY = b'RCH-login-transport-mask'


def masked_payload(password, username='admin'):
    nonce = bytes(range(16))
    data = password.encode('utf-8')
    masked = bytes(c ^ KEY[i % len(KEY)] ^ nonce[i % len(nonce)] for i, c in enumerate(data))
    return {'username': username, 'masked_password': base64.b64encode(masked).decode('ascii'),
            'mask_nonce': base64.b64encode(nonce).decode('ascii')}


class PasswordMaskTests(unittest.TestCase):
    def test_utf8_round_trip(self):
        value = 'secret-密码-👍'
        self.assertEqual(decode_masked_password(masked_payload(value)), value)

    def test_plaintext_field_is_not_a_login_payload(self):
        with self.assertRaises(ValueError):
            decode_masked_password({'username': 'admin', 'password': 'secret'})

    def test_rejects_bad_encoding_and_nonce(self):
        for payload in (
            {'masked_password': '%%%%', 'mask_nonce': base64.b64encode(bytes(range(16))).decode()},
            {'masked_password': 'YQ==', 'mask_nonce': 'AAAA'},
            {'masked_password': base64.b64encode(b'x' * 4097).decode(),
             'mask_nonce': base64.b64encode(bytes(range(16))).decode()},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    decode_masked_password(payload)


if __name__ == '__main__':
    unittest.main()
