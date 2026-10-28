"""Handshake logging uses the exact info payload transmitted to Server."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from client.bootstrap.connection_lifecycle import ClientConnectionLifecycle


def test_handshake_logs_full_payload_via_existing_logger_once(capsys):
    info = {
        'type': 'info', 'id': 'client-123', 'hostname': '测试主机',
        'command_manifest': [{'name': 'pyexec', 'cancel_policy': 'cooperative'}],
        'feature_manifest': {'watchdog': True, 'screen_view': False},
        'variable_manifest': [{'name': 'HOME'}],
    }
    client = SimpleNamespace(
        client_id='client-123', recovery_source='process_watchdog',
        server=Mock(), info=None,
    )
    lifecycle = ClientConnectionLifecycle(client)
    with patch('client.bootstrap.connection_lifecycle.ClientInfoBuilder') as builder, \
         patch('client.bootstrap.connection_lifecycle.logger.info') as log_info:
        builder.return_value.build.return_value = dict(info)
        lifecycle.handshake()

    expected = dict(info, recovery_source='process_watchdog')
    assert client.server.send.call_args.args[0] == expected
    assert client.info == expected
    assert capsys.readouterr().out == ''
    assert sum(call.args[0].startswith('Client handshake info:') for call in log_info.call_args_list) == 1
    log_info.assert_any_call('Client handshake info:\n%s', json.dumps(expected, ensure_ascii=False, indent=2))
    assert client.recovery_source == ''
    client.server.mark_connected.assert_called_once()


def test_reconnected_handshake_logs_current_payload_without_consumed_recovery_source(capsys):
    client = SimpleNamespace(client_id='client-123', recovery_source='', server=Mock(), info=None)
    with patch('client.bootstrap.connection_lifecycle.ClientInfoBuilder') as builder, \
         patch('client.bootstrap.connection_lifecycle.logger.info') as log_info:
        builder.return_value.build.return_value = {'type': 'info', 'id': 'client-123', 'feature_manifest': {'watchdog': False}}
        ClientConnectionLifecycle(client).handshake()
    sent = client.server.send.call_args.args[0]
    assert 'recovery_source' not in sent
    assert capsys.readouterr().out == ''
    assert log_info.call_args_list[0].args[1] == json.dumps(sent, ensure_ascii=False, indent=2)


def test_handshake_reaches_existing_console_logger_and_main_log_file(tmp_path, capsys, caplog):
    import logging

    info = {'type': 'info', 'id': 'client-123', 'feature_manifest': {'watchdog': True}}
    client = SimpleNamespace(client_id='client-123', recovery_source='', server=Mock(), info=None)
    handler = logging.FileHandler(tmp_path / 'client.log', encoding='utf-8')
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    try:
        with patch('client.bootstrap.connection_lifecycle.ClientInfoBuilder') as builder:
            builder.return_value.build.return_value = dict(info)
            ClientConnectionLifecycle(client).handshake()
    finally:
        root_logger.removeHandler(handler)
        handler.close()

    stdout = capsys.readouterr().out
    assert stdout == ''
    assert any(record.name == 'console_logger' and record.message.startswith('Client handshake info:')
               for record in caplog.records)
    assert '"feature_manifest"' in (tmp_path / 'client.log').read_text(encoding='utf-8')
    assert client.server.send.call_args.args[0] == info
