"""Isolated contract tests for the Script Library JSON action demo."""
import contextlib
import io
import json
import runpy
from pathlib import Path
from unittest.mock import patch


SCRIPT = (Path(__file__).resolve().parents[1] /
          'server/resources/scripts/test/misc/json_result_actions_probe.py')


def _invoke(tmp_path):
    text = io.StringIO()
    with patch('tempfile.gettempdir', return_value=str(tmp_path)), contextlib.redirect_stdout(text):
        runpy.run_path(str(SCRIPT))
    return json.loads(text.getvalue())


def test_probe_emits_only_valid_json_with_all_four_actions(tmp_path):
    rows = _invoke(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row['counter'] == 0
    assert len(row['_actions']) == 4
    assert row['_actions'][0]['confirm'] is False
    assert row['_actions'][0]['refresh'] is True
    assert row['_actions'][1]['refresh'] is False
    assert row['_actions'][2]['confirm'] is True
    assert row['_actions'][2]['refresh'] is True


def test_probe_increment_refresh_and_reset(tmp_path):
    rows = _invoke(tmp_path)
    increment = rows[0]['_actions'][0]['command']
    reset = rows[0]['_actions'][2]['command']
    assert increment.startswith('pyexec ')
    assert reset.startswith('pyexec ')
    exec(increment[len('pyexec '):], {})
    assert _invoke(tmp_path)[0]['counter'] == 1
    exec(increment[len('pyexec '):], {})
    assert _invoke(tmp_path)[0]['counter'] == 2
    exec(reset[len('pyexec '):], {})
    assert _invoke(tmp_path)[0]['counter'] == 0
