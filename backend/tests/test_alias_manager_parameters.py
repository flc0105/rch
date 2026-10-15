import unittest
from types import SimpleNamespace

from server.application.command.alias_manager import AliasManager
from server.application.web.quick_action_api import WebQuickActionApi


class AliasManagerParameterTests(unittest.TestCase):
    def setUp(self):
        self.manager = AliasManager.__new__(AliasManager)
        self.manager.aliases = self.manager._create_empty_aliases()

    def test_extract_parameters_deduplicates_names_in_first_appearance_order(self):
        parameters = self.manager.extract_parameters(
            'shell tool --input <path> --backup <path> --env <env> --again <path>'
        )

        self.assertEqual(['path', 'env'], [item['name'] for item in parameters])
        self.assertEqual([0, 2], [item['position'] for item in parameters])
        self.assertEqual(['<path>', '<env>'], [item['placeholder'] for item in parameters])

    def test_resolve_alias_definition_reuses_same_named_parameter(self):
        self.manager.aliases['common']['copy3'] = (
            'shell tool --input <path> --backup <path> --log <path>'
        )

        resolved = self.manager.resolve_alias_definition('copy3', ['/tmp/source'], 'common')

        self.assertEqual(
            'shell tool --input /tmp/source --backup /tmp/source --log /tmp/source',
            resolved['command'],
        )
        self.assertEqual(['path'], [item['name'] for item in resolved['parameters']])
        self.assertEqual(['/tmp/source'], resolved['arguments'])

    def test_resolve_alias_definition_binds_unique_names_positionally(self):
        self.manager.aliases['common']['deploy'] = (
            'deploy <host> --source <path> --backup <path> --env <env>'
        )

        resolved = self.manager.resolve_alias_definition(
            'deploy',
            ['server01', '/tmp/app', 'prod'],
            'common',
        )

        self.assertEqual(
            'deploy server01 --source /tmp/app --backup /tmp/app --env prod',
            resolved['command'],
        )
        self.assertEqual(['host', 'path', 'env'], [item['name'] for item in resolved['parameters']])

    def test_resolve_alias_keeps_existing_positional_invocation_for_unique_names(self):
        self.manager.aliases['common']['zip'] = 'zip <src> <dst>'

        resolved = self.manager.resolve_alias('zip', 'one two')

        self.assertEqual('zip one two', resolved['command'])

    def test_resolve_alias_reuses_name_with_quoted_positional_value(self):
        self.manager.aliases['common']['echo_twice'] = 'shell echo "<text>" && echo "<text>"'

        resolved = self.manager.resolve_alias('echo_twice', '"hello world"')

        self.assertEqual('shell echo "hello world" && echo "hello world"', resolved['command'])

    def test_argument_count_is_based_on_unique_parameter_names(self):
        self.manager.aliases['common']['copy3'] = 'shell cp <path> <path> && echo <path>'

        with self.assertRaisesRegex(ValueError, r'Expected 1 argument\(s\), got 2'):
            self.manager.resolve_alias('copy3', 'one two')

    def test_different_parameter_names_keep_separate_values(self):
        self.manager.aliases['common']['pair'] = 'shell echo <left> <right> <left>'

        resolved = self.manager.resolve_alias('pair', 'A B')

        self.assertEqual('shell echo A B A', resolved['command'])

    def test_named_invocation_binds_by_name_independent_of_input_order(self):
        self.manager.aliases['common']['deploy'] = (
            'deploy <host> --source <path> --backup <path> --env <env>'
        )

        resolved = self.manager.resolve_alias(
            'deploy',
            '--env prod --host server01 --path /tmp/app',
        )

        self.assertEqual(
            'deploy server01 --source /tmp/app --backup /tmp/app --env prod',
            resolved['command'],
        )

    def test_named_invocation_supports_equals_syntax(self):
        self.manager.aliases['common']['pair'] = 'shell echo <left> <right> <left>'

        resolved = self.manager.resolve_alias('pair', '--right=B --left=A')

        self.assertEqual('shell echo A B A', resolved['command'])

    def test_named_invocation_reports_missing_argument_by_name(self):
        self.manager.aliases['common']['pair'] = 'shell echo <src> <dst>'

        with self.assertRaisesRegex(ValueError, r'^Missing argument: dst$'):
            self.manager.resolve_alias('pair', '--src A')

    def test_named_invocation_rejects_unknown_argument(self):
        self.manager.aliases['common']['pair'] = 'shell echo <src> <dst>'

        with self.assertRaisesRegex(ValueError, r'^Unknown argument: nope$'):
            self.manager.resolve_alias('pair', '--src A --nope B --dst C')

    def test_named_invocation_rejects_duplicate_argument(self):
        self.manager.aliases['common']['pair'] = 'shell echo <src> <dst>'

        with self.assertRaisesRegex(ValueError, r'^Duplicate argument: src$'):
            self.manager.resolve_alias('pair', '--src A --src B --dst C')

    def test_named_invocation_rejects_mixed_positional_tokens(self):
        self.manager.aliases['common']['pair'] = 'shell echo <src> <dst>'

        with self.assertRaisesRegex(ValueError, r'^Cannot mix positional and named arguments$'):
            self.manager.resolve_alias('pair', '--src A B --dst C')

    def test_only_cli_safe_names_are_placeholders(self):
        command = 'shell echo <user_name> <client-id> <hello world> <2bad> <some/path>'
        parameters = self.manager.extract_parameters(command)

        self.assertEqual(['user_name', 'client-id'], [item['name'] for item in parameters])
        self.manager.aliases['common']['safe'] = command
        resolved = self.manager.resolve_alias('safe', '--client-id C1 --user_name Alice')
        self.assertEqual(
            'shell echo Alice C1 <hello world> <2bad> <some/path>',
            resolved['command'],
        )

    def test_shell_redirections_are_not_placeholders(self):
        command = (
            "osascript -e 'do shell script \"nohup ${rch:launch_command} "
            "</dev/null >/var/tmp/rchclient.log 2>&1 &\" with administrator privileges'"
        )
        self.manager.aliases['common']['sudo_client'] = command

        self.assertEqual([], self.manager.extract_parameters(command))
        self.assertEqual(command, self.manager.resolve_alias('sudo_client')['command'])

    def test_valid_parameter_with_redirections(self):
        command = 'shell cat <input_path> </dev/null >/tmp/out.log 2>&1'
        self.manager.aliases['common']['catfile'] = command

        self.assertEqual(['input_path'], self.manager._extract_required_args(command))
        self.assertEqual(
            'shell cat /tmp/in </dev/null >/tmp/out.log 2>&1',
            self.manager.resolve_alias('catfile', '--input_path /tmp/in')['command'],
        )

    def test_named_invocation_preserves_quoted_values_with_spaces(self):
        self.manager.aliases['common']['say'] = 'shell echo "<text>" <count>'

        resolved = self.manager.resolve_alias('say', '--count 2 --text "hello world"')

        self.assertEqual('shell echo "hello world" 2', resolved['command'])

    def test_double_dash_forces_positional_value_that_starts_with_dashes(self):
        self.manager.aliases['common']['one'] = 'shell echo <value>'

        resolved = self.manager.resolve_alias('one', '-- --version')

        self.assertEqual('shell echo --version', resolved['command'])



class QuickActionNameOrientedParameterTests(unittest.TestCase):
    def setUp(self):
        self.manager = AliasManager.__new__(AliasManager)
        self.manager.aliases = self.manager._create_empty_aliases()
        self.manager.aliases['common']['copy3'] = 'shell cp <path> <path> && echo <path>'
        self.session = SimpleNamespace(session_info=SimpleNamespace(os_type='', os_alias=''))
        self.server = SimpleNamespace(
            get_target_connection_by_client_id=lambda _client_id: self.session,
        )
        self.submissions = []

        class _CommandExecutionApi:
            def __init__(inner_self, submissions):
                inner_self.submissions = submissions

            def submit_web_command(inner_self, client_id, command, **kwargs):
                inner_self.submissions.append((client_id, command, kwargs))
                return {'task_id': 'task-1'}

        self.api = WebQuickActionApi(
            self.server,
            self.manager,
            _CommandExecutionApi(self.submissions),
        )

    def test_quick_action_item_exposes_one_field_for_repeated_name(self):
        item = self.api._build_item(
            'common',
            'copy3',
            self.manager.aliases['common']['copy3'],
            'common',
            {},
        )

        self.assertEqual(['path'], [parameter['name'] for parameter in item['parameters']])

    def test_quick_action_ignores_shell_redirection(self):
        command = 'shell cat <input_path> </dev/null >/tmp/out.log 2>&1'
        item = self.api._build_item('common', 'catfile', command, 'common', {})

        self.assertEqual(['input_path'], [p['name'] for p in item['parameters']])

    def test_quick_action_dialog_execution_reuses_one_value(self):
        result = self.api.execute_quick_action(
            'client-1',
            'common',
            'copy3',
            arguments=['/tmp/a'],
            presentation='dialog',
            run_id='run-1',
        )

        expected = 'shell cp /tmp/a /tmp/a && echo /tmp/a'
        self.assertEqual(expected, result['resolved_command'])
        self.assertEqual(expected, result['submitted_command'])
        self.assertEqual(expected, self.submissions[0][1])

    def test_quick_action_terminal_keeps_existing_positional_alias_syntax(self):
        result = self.api.execute_quick_action(
            'client-1',
            'common',
            'copy3',
            arguments=['/tmp/a'],
            presentation='terminal',
            run_id='run-1',
        )

        self.assertEqual('copy3 /tmp/a', result['display_command'])
        self.assertEqual('copy3 /tmp/a', result['submitted_command'])
        self.assertEqual('copy3 /tmp/a', self.submissions[0][1])


if __name__ == '__main__':
    unittest.main()
