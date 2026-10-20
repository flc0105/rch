import unittest

from server.application.web.script_api import WebScriptApi


class FakeCommandApi:
    def __init__(self):
        self.calls = []

    def submit_web_command(self, client_id, command, **kwargs):
        self.calls.append((client_id, command, kwargs))
        return {'task_id': 'task-123'}


class FakeScriptCatalog:
    def list_scripts(self):
        return [{'script_name': 'tools/hello', 'metadata': {'params': [
            {'name': 'message', 'type': 'string', 'required': True},
        ]}}]


class ScriptPresentationTests(unittest.TestCase):
    def setUp(self):
        self.commands = FakeCommandApi()
        self.api = WebScriptApi(self.commands, FakeScriptCatalog())

    def test_dialog_routes_its_output_using_run_id_without_changing_script_command(self):
        result = self.api.run_script(
            'device-1', 'tools/hello', params={'message': 'Hello World'},
            tab_id='tab-3', presentation='dialog', run_id='dialog-456',
        )
        self.assertEqual('task-123', result['task_id'])
        client, command, kwargs = self.commands.calls[0]
        self.assertEqual('device-1', client)
        self.assertTrue(command.startswith('script run '))
        self.assertEqual('tab-3', kwargs['tab_id'])
        self.assertEqual({
            'script_run': True,
            'script_run_id': 'dialog-456',
            'script_run_name': 'tools/hello',
            'script_run_arguments': {'message': 'Hello World'},
            'script_run_presentation': 'dialog',
        }, kwargs['metadata'])
        self.assertNotIn('dialog-456', command)

    def test_terminal_keeps_standard_script_submission(self):
        self.api.run_script(
            'device-1', 'tools/hello', params={'message': 'Hi'},
            presentation='terminal',
        )
        client, command, kwargs = self.commands.calls[0]
        self.assertEqual('device-1', client)
        self.assertTrue(command.startswith('script run '))
        self.assertEqual('terminal', kwargs['metadata']['script_run_presentation'])
        self.assertEqual('', kwargs['metadata']['script_run_id'])

    def test_missing_or_invalid_presentation_is_rejected(self):
        for presentation in ['', None, 'other']:
            with self.subTest(presentation=presentation):
                with self.assertRaisesRegex(ValueError, 'presentation must be'):
                    self.api.run_script('device-1', 'tools/hello', presentation=presentation)
        self.assertEqual([], self.commands.calls)

    def test_dialog_requires_run_id(self):
        with self.assertRaisesRegex(ValueError, 'run_id is required'):
            self.api.run_script('device-1', 'tools/hello', presentation='dialog')
        self.assertEqual([], self.commands.calls)


if __name__ == '__main__':
    unittest.main()
