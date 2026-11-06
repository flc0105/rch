"""Readline/libedit editing regression tests for the remote RCH CLI."""

import importlib.util
import io
import pathlib
import sys
import unittest
from unittest.mock import patch

CLI_PATH = pathlib.Path(__file__).resolve().parents[1] / 'rchcli' / 'rchcli.py'
spec = importlib.util.spec_from_file_location('rchcli_readline_under_test', CLI_PATH)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class FakeApi:
    def command_candidates(self, client_id):
        return [{'insert_text': 'getinfo', 'title': 'getinfo'}]

    def completions(self, client_id, text):
        return [{'insert_text': 'download /bin', 'kind': 'directory'}]


class FakeReadline:
    def __init__(self, backend=None, doc='Readline test double'):
        self.backend = backend
        self.__doc__ = doc
        self.completer = None
        self.delims = ' \t\n'
        self.binding = None
        self.buffer = ''
        self.begin_index = 0
        self.end_index = None
        self.startup_hook = None
        self.history = ['previous command']
        self.insertions = []
        self.redraws = 0

    def get_completer(self):
        return self.completer

    def set_completer(self, value):
        self.completer = value

    def get_completer_delims(self):
        return self.delims

    def set_completer_delims(self, value):
        self.delims = value

    def parse_and_bind(self, value):
        self.binding = value

    def get_line_buffer(self):
        return self.buffer

    def get_endidx(self):
        return len(self.buffer) if self.end_index is None else self.end_index

    def get_begidx(self):
        return self.begin_index

    def set_startup_hook(self, value=None):
        self.startup_hook = value

    def insert_text(self, value):
        self.insertions.append(value)
        self.buffer += value

    def redisplay(self):
        self.redraws += 1


def make_console(*, reader=None, color='always'):
    rc = cli.RemoteConsole(FakeApi(), None, 'tab', reader=reader,
                           output=io.StringIO(), color=color)
    rc.selected = {'client_id': 'device-1', 'name': 'mac'}
    return rc


class ReadlineSetupTests(unittest.TestCase):
    def _setup(self, backend, doc='Readline test double'):
        fake = FakeReadline(backend, doc)
        rc = make_console()
        with patch.dict(sys.modules, {'readline': fake}):
            restore = rc._install_readline_completion()
        self.assertIsNotNone(restore)
        return rc, fake, restore

    def test_mac_editline_tab_binding_and_remote_completion(self):
        rc, rd, restore = self._setup('editline')
        self.assertEqual(rd.binding, 'bind ^I rl_complete')
        rd.buffer = 'get'
        self.assertEqual(rd.completer('', 0), 'getinfo')
        self.assertIsNone(rd.completer('', 1))
        restore()
        self.assertIsNone(rc._readline)
        self.assertEqual(rd.delims, ' \t\n')
        self.assertIsNone(rd.completer)

    def test_older_mac_libedit_doc_detected(self):
        _, rd, restore = self._setup(None, 'This module uses libedit readline emulation')
        self.assertEqual(rd.binding, 'bind ^I rl_complete')
        restore()

    def test_gnu_readline_tab_binding_and_path_insert(self):
        rc, rd, restore = self._setup('readline')
        self.assertEqual(rd.binding, 'tab: complete')
        rd.buffer = 'download /b'
        self.assertEqual(rd.completer('', 0), 'download /bin/')
        restore()


    def test_mac_libedit_replaces_active_path_word_not_whole_command(self):
        rc, rd, restore = self._setup('editline')
        rd.buffer = 'download /b'
        rd.begin_index = len('download ')
        # The Server always returns the *complete* command, as Web expects.
        candidate = rd.completer('/b', 0)
        self.assertEqual(candidate, '/bin/')
        edited = rd.buffer[:rd.begin_index] + candidate + rd.buffer[rd.get_endidx():]
        self.assertEqual(edited, 'download /bin/')
        restore()

    def test_mac_libedit_correctly_completes_users_directory(self):
        rc, rd, restore = self._setup('editline')
        rc.completion_candidates = lambda raw: [
            {'insert_text': 'download /Users', 'kind': 'directory'}]
        rd.buffer = 'download /Use'
        rd.begin_index = len('download ')
        candidate = rd.completer('/Use', 0)
        self.assertEqual(candidate, '/Users/')
        self.assertEqual(rd.buffer[:rd.begin_index] + candidate,
                         'download /Users/')
        restore()

    def test_path_filter_keeps_case_sensitive_match_and_prevents_libedit_common_prefix_regression(self):
        rc, rd, restore = self._setup('editline')
        rc.api.completions = lambda client_id, raw: [
            {'insert_text': 'cd /Users', 'kind': 'directory'},
            {'insert_text': 'cd /usr', 'kind': 'directory'},
        ]
        rd.buffer = 'cd /Us'
        rd.begin_index = 0

        candidates = rc.completion_candidates('cd /Us')
        self.assertEqual([item['insert_text'] for item in candidates], ['cd /Users'])
        self.assertEqual(rd.completer('cd /Us', 0), 'cd /Users/')
        self.assertIsNone(rd.completer('cd /Us', 1))
        restore()

    def test_path_filter_remains_case_sensitive_for_lowercase_prefix(self):
        rc = make_console()
        rc.api.completions = lambda client_id, raw: [
            {'insert_text': 'cd /Users', 'kind': 'directory'},
            {'insert_text': 'cd /usr', 'kind': 'directory'},
        ]
        candidates = rc.completion_candidates('cd /us')
        self.assertEqual([item['insert_text'] for item in candidates], ['cd /usr'])

    def test_edit_is_suggested_as_local_command_and_uses_remote_path_completion(self):
        rc = make_console()
        local = rc.completion_candidates('edi')
        self.assertIn('edit', [item['insert_text'] for item in local])

        rc.api.completions = lambda client_id, raw: [
            {'insert_text': 'edit /Users/flc/Desktop', 'kind': 'directory'},
            {'insert_text': 'edit /Users/flc/notes.txt', 'kind': 'file'},
        ]
        paths = rc.completion_candidates('edit /Users/flc/')
        self.assertEqual(
            [item['insert_text'] for item in paths],
            ['edit /Users/flc/Desktop', 'edit /Users/flc/notes.txt'],
        )

    def test_mac_libedit_multiword_job_name_no_prefix_duplication(self):
        rc, rd, restore = self._setup('editline')
        rc.completion_candidates = lambda raw: [
            {'insert_text': 'job logs clipboard_monitor', 'kind': 'job'}]
        rd.buffer = 'job logs clip'
        rd.begin_index = len('job logs ')
        candidate = rd.completer('clip', 0)
        self.assertEqual(candidate, 'clipboard_monitor')
        self.assertEqual(rd.buffer[:rd.begin_index] + candidate,
                         'job logs clipboard_monitor')
        restore()

    def test_mac_libedit_uses_text_if_begin_index_is_inconsistent(self):
        rc, rd, restore = self._setup('editline')
        rc.completion_candidates = lambda raw: [
            {'insert_text': 'download /Users', 'kind': 'directory'}]
        rd.buffer = 'download /Use'
        rd.begin_index = 0  # An inconsistent libedit boundary.
        candidate = rd.completer('/Use', 0)
        self.assertEqual(candidate, '/Users/')
        restore()

    def test_gnu_readline_full_line_replacement_does_not_strip_command(self):
        rc, rd, restore = self._setup('readline')
        rd.buffer = 'download /b'
        rd.begin_index = 0
        candidate = rd.completer('download /b', 0)
        self.assertEqual(candidate, 'download /bin/')
        restore()

    def test_mac_empty_argument_word_does_not_repeat_command(self):
        rc, rd, restore = self._setup('editline')
        rc.completion_candidates = lambda raw: [
            {'insert_text': 'job logs clipboard_monitor', 'kind': 'job'}]
        rd.buffer = 'job logs '
        rd.begin_index = 0  # Empty active word, libedit reports stale begin.
        self.assertEqual(rd.completer('', 0), 'clipboard_monitor')
        restore()

    def test_mid_line_completion_does_not_modify_buffer(self):
        rc, rd, restore = self._setup('editline')
        rd.buffer = 'download /Use --json'
        rd.begin_index = len('download ')
        rd.end_index = len('download /Use')
        self.assertIsNone(rd.completer('/Use', 0))
        restore()

    def test_ansi_prompt_escapes_are_not_counted_as_columns(self):
        rc, _, restore = self._setup('editline')
        prompt = rc._repl_prompt('MacBook', rc.GREEN)
        self.assertEqual(prompt, '\x01\x1b[92m\x02MacBook> \x01\x1b[0m\x02')
        self.assertEqual(prompt.replace('\x01', '').replace('\x02', ''),
                         '\x1b[92mMacBook> \x1b[0m')
        restore()
        self.assertEqual(rc._repl_prompt('MacBook', rc.GREEN),
                         '\x1b[92mMacBook> \x1b[0m')

    def test_draft_prefilled_into_editable_buffer_and_hook_removed(self):
        rc, rd, restore = self._setup('editline')
        rc.reader = lambda prompt: (rd.startup_hook(), rd.get_line_buffer())[1]
        result, editable = rc._read_repl_input('mac> ', 'download /bin/')
        self.assertEqual(result, 'download /bin/')
        self.assertTrue(editable)
        self.assertEqual(rd.insertions, ['download /bin/'])
        self.assertEqual(rd.redraws, 0)  # Extra redisplay duplicates the colored prompt.
        self.assertIsNone(rd.startup_hook)
        restore()

    def test_draft_readline_history_replacement_never_reappends_stale_text(self):
        rc, rd, restore = self._setup('editline')
        rc.completion_draft = 'download /bin/'
        responses = ['whoami', 'exit', 'quit']
        rc.reader = lambda prompt: responses.pop(0)
        rc._readline = rd
        sent = []
        rc.execute = sent.append
        rc._install_readline_completion = lambda: restore
        rc.repl()
        self.assertEqual(sent, ['whoami'])  # Up-arrow selected history, not old draft + whoami
        restore()

    def test_no_readline_keeps_old_draft_prompt_behavior(self):
        rc = make_console(reader=lambda prompt: 'bash')
        rc.completion_draft = 'download /bin/'
        result, editable = rc._read_repl_input('mac> download /bin/', rc.completion_draft)
        self.assertEqual((result, editable), ('bash', False))
        self.assertIsNone(rc._install_readline_completion())


if __name__ == '__main__':
    unittest.main()
