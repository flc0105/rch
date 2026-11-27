"""Previously missed ACMD success paths, Result projection and PTY cwd forwarding."""
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from client.commands.acmd.common.inspection import image_info, sqlite_query
from core.utils.command_output import (ResultDataShape, StructuredCommandResult,
    project_result_events, project_result_output_texts, result_visible_text)
from core.protocol.result_envelope import ResultEvent
from core.protocol.result_envelope import result_wire_event
from rchcli.rchcli import RemoteConsole
from server.application.terminal.pty_session_service import PtySessionService


def _context():
    return SimpleNamespace(path_resolver=SimpleNamespace(require_existing_file=lambda path: str(Path(path).resolve())))


def test_sqlite_query_success_returns_native_rows_and_default_table(tmp_path):
    db = tmp_path / 'sample.sqlite3'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE sample (num INTEGER, value TEXT)')
        conn.execute("INSERT INTO sample VALUES (5, 'ok')")
    result = sqlite_query(_context(), {'db': str(db), 'query': 'SELECT num, value FROM sample', 'limit': None})
    assert isinstance(result, StructuredCommandResult)
    assert result.status == 1 and result.shape == ResultDataShape.TABLE
    assert result.data == [{'num': 5, 'value': 'ok'}]


def test_image_info_success_returns_native_object(tmp_path):
    import pytest
    image_module = pytest.importorskip('PIL.Image')
    path = tmp_path / 'sample.png'
    image_module.new('RGB', (2, 3)).save(path)
    result = image_info(_context(), {'path': str(path)})
    assert isinstance(result, StructuredCommandResult)
    assert result.status == 1 and result.shape == ResultDataShape.FLAT
    assert result.data['width'] == 2 and result.data['height'] == 3


def test_cli_history_and_live_terminal_use_identical_projection():
    data = [{'pid': 7, 'name': 'test'}]
    for fmt in ('table', 'records', 'json'):
        event = result_wire_event(1, 1, StructuredCommandResult(
            status=1, data=data, shape=ResultDataShape.TABLE,
            formats=('table', 'records', 'json')).as_event(requested=fmt))
        chunk = ResultEvent(event)
        shown = next(project_result_events([chunk]))
        assert shown.event is event and shown.visible_text() == result_visible_text(event)
        assert project_result_output_texts([event]) == [shown.visible_text()]
        assert list(RemoteConsole._activity_output([event], project_result_output_texts([event])))[0][0] == shown.visible_text()
    error = result_wire_event(2, 0, 'Business failed')
    assert result_visible_text(error) is None
    assert list(RemoteConsole._activity_output([error]))[0][0] == 'Business failed'


def test_pty_create_session_forwards_requested_client_cwd():
    sent = []
    connection = SimpleNamespace(send=sent.append)
    server = SimpleNamespace(get_target_connection_by_client_id=lambda _: connection)
    service = PtySessionService(server)
    result = service.create_session('client', cwd='C:\\My Projects\\測試', cols=80, rows=24)
    assert result['status'] == 'opening'
    assert sent[0]['type'] == 'pty_open'
    assert sent[0]['cwd'] == 'C:\\My Projects\\測試'
