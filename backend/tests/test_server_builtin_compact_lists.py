"""Server list presentation: compact text and unchanged detailed/JSON contracts."""

import importlib
import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.utils.command_output import ResultDataShape, render_result_payload
from server.application.command.job_builtin_support import JobBuiltinSupport
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY


@pytest.fixture
def supports():
    # Only import the listing support functions: admin auth config normally needs
    # Werkzeug, which is unnecessary for these isolated presentation tests.
    config = types.ModuleType('server.config.config')
    config.COMMAND_HISTORY_RECENT_LIMIT = 100
    config.SCRIPT_PATH = '/unused/scripts'
    config.ALIAS_PATH = '/unused/aliases.json'
    history = types.ModuleType('server.application.history.quick_history')
    history.QuickHistoryRecordPolicy = type('QuickHistoryRecordPolicy', (), {})
    name = 'server.application.command.builtin_command_support'
    with patch.dict(sys.modules, {'server.config.config': config,
                                  'server.application.history.quick_history': history}):
        sys.modules.pop(name, None)
        module = importlib.import_module(name)
        try:
            yield module
        finally:
            sys.modules.pop(name, None)


def _result(support, command, tail):
    invocation = SERVER_COMMAND_REGISTRY.parse_invocation(command, tail)
    result = next(iter(support(invocation)))
    assert result[0] == 1 and result.eof and result.terminal_authoritative
    assert result.event['status'] == 'success'
    return result


@pytest.mark.parametrize('name', ['script', 'job', 'alias'])
def test_format_table_replaces_detail_in_declared_schema(name):
    for tail in ('', 'list'):
        invocation = SERVER_COMMAND_REGISTRY.parse_invocation(name, tail)
        assert invocation.action == 'list'
        assert 'detail' not in invocation.arguments
    for tail in ('list --format table', 'list -f table'):
        invocation = SERVER_COMMAND_REGISTRY.parse_invocation(name, tail)
        assert invocation.arguments['format'] == 'table'
    for tail in ('list --detail', 'list -d'):
        with pytest.raises(ValueError, match='Unknown option'):
            SERVER_COMMAND_REGISTRY.parse_invocation(name, tail)



def test_script_list_keeps_catalog_for_json_and_detail(supports):
    script = supports.ScriptBuiltinSupport.__new__(supports.ScriptBuiltinSupport)
    script.list_script_catalog = lambda: [
        {'path': 'common/alpha.py', 'display_name': 'Alpha', 'description': 'test',
         'metadata': {'params': [{'name': 'target'}]}},
        {'path': 'mac/beta.py', 'display_name': 'Beta', 'description': 'other',
         'metadata': {'params': {'limit': {}}}},
    ]
    run = lambda tail: _result(script.script, 'script', tail)
    rows = [{'name': 'common/alpha.py', 'display_name': 'Alpha', 'description': 'test', 'params': ['target']},
            {'name': 'mac/beta.py', 'display_name': 'Beta', 'description': 'other', 'params': ['limit']}]
    assert run('list')[1] == 'common/alpha.py\nmac/beta.py'
    assert run('list --format table')[1] == render_result_payload(run('list --format table').event,
                                                        view='data', shape=ResultDataShape.TABLE)
    assert json.loads(run('list --json')[1]) == rows
    assert json.loads(run('list --format table --json')[1]) == rows
    assert run('list').event['data'] == rows


def test_job_list_keeps_catalog_for_json_and_detail():
    job = JobBuiltinSupport.__new__(JobBuiltinSupport)
    job.conn = SimpleNamespace(session_info=SimpleNamespace(os_alias='mac'))
    job.job_catalog_service = SimpleNamespace(list_background_job_catalog=lambda: [
        {'job_name': 'mac/watch', 'display_name': 'Watch', 'description': 'Watch events',
         'metadata': {'platforms': ['mac']}},
        {'job_name': 'linux/other', 'display_name': 'Other', 'description': '',
         'metadata': {'platforms': ['linux']}},
    ])
    run = lambda tail: _result(job.execute_subcommand, 'job', tail)
    assert run('list')[1] == 'mac/watch'
    assert 'Watch events' in run('list --format table')[1]
    assert json.loads(run('list --json')[1]) == [
        {'name': 'mac/watch', 'display_name': 'Watch', 'description': 'Watch events'}]
    assert run('list').event['data'] == json.loads(run('list --json')[1])


def test_alias_list_keeps_resolved_platform_and_command_for_json(supports):
    alias = supports.AliasBuiltinSupport.__new__(supports.AliasBuiltinSupport)
    alias._build_resolved_alias_payload = lambda: [
        {'platform': 'common', 'alias': 'll', 'command': 'shell ls -la'},
        {'platform': 'mac', 'alias': 'psx', 'command': 'acmd ps --json'},
    ]
    run = lambda tail: _result(alias.alias, 'alias', tail)
    assert run('list')[1] == 'll = shell ls -la\npsx = acmd ps --json'
    assert run('list --format lines')[1] == 'll\npsx'
    assert run('-f lines')[1] == 'll\npsx'
    assert 'platform' in run('--format table')[1]
    assert json.loads(run('--json')[1]) == run('').event['data']
    assert json.loads(run('list --format table --json')[1]) == run('').event['data']


@pytest.mark.parametrize('name', ['script', 'job', 'alias'])
def test_list_rejects_unknown_flag(name):
    with pytest.raises(ValueError):
        SERVER_COMMAND_REGISTRY.parse_invocation(name, 'list --unknown')


def test_alias_empty_result_is_readable(supports):
    alias = supports.AliasBuiltinSupport.__new__(supports.AliasBuiltinSupport)
    alias._build_resolved_alias_payload = lambda: []
    assert _result(alias.alias, 'alias', '')[1] == 'No aliases configured'
    assert _result(alias.alias, 'alias', '--format lines')[1] == 'No aliases configured'
    assert json.loads(_result(alias.alias, 'alias', '--json')[1]) == []


def test_script_empty_result_keeps_empty_json(supports):
    script = supports.ScriptBuiltinSupport.__new__(supports.ScriptBuiltinSupport)
    script.list_script_catalog = lambda: []
    assert _result(script.script, 'script', '')[1] == 'No data to display'
    assert json.loads(_result(script.script, 'script', '--json')[1]) == []


def test_job_empty_result_keeps_empty_json():
    job = JobBuiltinSupport.__new__(JobBuiltinSupport)
    job.conn = SimpleNamespace(session_info=SimpleNamespace(os_alias='linux'))
    job.job_catalog_service = SimpleNamespace(list_background_job_catalog=lambda: [])
    assert _result(job.execute_subcommand, 'job', '')[1] == 'No background jobs available'
    assert json.loads(_result(job.execute_subcommand, 'job', '--json')[1]) == []
