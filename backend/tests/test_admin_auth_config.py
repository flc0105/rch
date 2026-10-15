import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import check_password_hash

from server.config.admin_auth import load_admin_auth


class AdminAuthConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name) / 'runtime'
        self.runtime.mkdir()
        self.path = self.runtime / 'auth.json'

    def initialize(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            auth = load_admin_auth(str(self.path))
        return auth, output.getvalue()

    def test_first_start_creates_valid_credentials_and_prints_password_once(self):
        auth, output = self.initialize()
        password = output.split('Initial administrator password: ', 1)[1].strip()
        self.assertEqual(auth['username'], 'admin')
        self.assertTrue(check_password_hash(auth['password'], password))
        self.assertNotIn(password, self.path.read_text())
        self.assertGreaterEqual(len(auth['api_token']), 32)
        self.assertGreaterEqual(len(auth['session_secret']), 32)
        if os.name == 'posix':
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(self.path.read_text()), auth)

        again, second_output = self.initialize()
        self.assertEqual(again, auth)
        self.assertEqual(second_output, '')

    def test_plain_password_reset_preserves_token_and_secret(self):
        initial, output = self.initialize()
        old_password = output.split('Initial administrator password: ', 1)[1].strip()
        changed = dict(initial, password='plain:replaced-secret-password')
        self.path.write_text(json.dumps(changed), encoding='utf-8')
        updated, reset_output = self.initialize()
        self.assertEqual(reset_output, '')
        self.assertTrue(check_password_hash(updated['password'], 'replaced-secret-password'))
        self.assertFalse(check_password_hash(updated['password'], old_password))
        for key in ('api_token', 'session_secret', 'username'):
            self.assertEqual(initial[key], updated[key])
        self.assertEqual(json.loads(self.path.read_text()), updated)
        self.assertNotIn('plain:', self.path.read_text())

    def test_missing_configuration_creates_fresh_credentials(self):
        original, _ = self.initialize()
        self.path.unlink()
        regenerated, output = self.initialize()
        self.assertIn('Initial administrator password:', output)
        self.assertNotEqual(original['password'], regenerated['password'])
        self.assertNotEqual(original['api_token'], regenerated['api_token'])
        self.assertNotEqual(original['session_secret'], regenerated['session_secret'])

    def test_invalid_configuration_fails_closed(self):
        cases = ('{bad json', '{}', '{"username":"admin"}')
        for content in cases:
            with self.subTest(content=content):
                self.path.write_text(content, encoding='utf-8')
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    self.initialize()
                self.assertEqual(self.path.read_text(), content)

    def test_empty_plain_password_fails_closed(self):
        original, _ = self.initialize()
        self.path.write_text(json.dumps(dict(original, password='plain:')))
        with self.assertRaisesRegex(ValueError, 'Empty plaintext'):
            self.initialize()

    def test_other_password_formats_fail_closed(self):
        original, _ = self.initialize()
        for password in ('secret-in-clear', 'md5$abc', 'scrypt:not-valid'):
            with self.subTest(password=password):
                self.path.write_text(json.dumps(dict(original, password=password)))
                with self.assertRaisesRegex(ValueError, 'Invalid administrator password hash'):
                    self.initialize()


if __name__ == '__main__':
    unittest.main()
