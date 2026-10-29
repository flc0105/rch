"""Legacy HTTP transfer has private network timeouts; Cancelable stays unchanged."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from client.commands.strategies.http_transfer.legacy import LegacyHttpTransferStrategy
from client.commands.strategies.http_transfer.cancelable import CancelableHttpTransferStrategy


def test_legacy_upload_sets_connect_and_read_timeout(tmp_path, monkeypatch):
    path = tmp_path / 'x.dat'
    path.write_bytes(b'file')
    session = SimpleNamespace(post=Mock(return_value='ok'), close=Mock())
    strategy = LegacyHttpTransferStrategy(SimpleNamespace(_set_cancel_policy=Mock()))
    monkeypatch.setattr(strategy, 'create_http_session', lambda: session)
    assert strategy.upload_file(str(path), 'http://example.invalid/upload', {'key': 'value'}) == 'ok'
    assert session.post.call_args.kwargs['timeout'] == (15, 120)
    session.close.assert_called_once()


def test_legacy_download_sets_timeout_and_still_writes_stream(tmp_path, monkeypatch):
    response = Mock()
    response.headers = {'Content-Length': '4'}
    response.iter_content.return_value = [b'ab', b'cd']
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    session = SimpleNamespace(get=Mock(return_value=response), close=Mock())
    strategy = LegacyHttpTransferStrategy(SimpleNamespace(_set_cancel_policy=Mock()))
    monkeypatch.setattr(strategy, 'create_http_session', lambda: session)
    received = []
    path = tmp_path / 'download.txt'
    strategy.download_file('http://example.invalid/file', str(path), lambda n, total: received.append((n, total)))
    assert path.read_bytes() == b'abcd'
    assert received == [(2, 4), (4, 4)]
    assert session.get.call_args.kwargs == {'stream': True, 'timeout': (15, 120)}
    session.close.assert_called_once()


def test_legacy_network_timeout_raises_and_closes_session(tmp_path, monkeypatch):
    path = tmp_path / 'x.dat'
    path.write_bytes(b'file')
    session = SimpleNamespace(post=Mock(side_effect=requests.exceptions.ReadTimeout('waited')), close=Mock())
    strategy = LegacyHttpTransferStrategy(SimpleNamespace(_set_cancel_policy=Mock()))
    monkeypatch.setattr(strategy, 'create_http_session', lambda: session)
    with pytest.raises(requests.exceptions.ReadTimeout):
        strategy.upload_file(str(path), 'http://example.invalid/upload', {})
    session.close.assert_called_once()


def test_cancelable_strategy_code_has_no_legacy_timeout(tmp_path):
    from pathlib import Path
    code = (Path(__file__).resolve().parents[2] / 'client/commands/strategies/http_transfer/cancelable.py').read_text()
    assert '_NETWORK_TIMEOUT' not in code
    assert 'timeout=self._NETWORK_TIMEOUT' not in code
    assert CancelableHttpTransferStrategy.MODE_NAME == 'cancelable'
