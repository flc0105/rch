"""Chassis classification and handshake/variable contract tests."""

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import core.device.chassis_type as chassis
from client.runtime import command_variable_resolver as variable_module
from client.runtime.command_variable_resolver import CommandVariableResolver
from client.connection import handshake as builder_module
from client.connection.handshake import ClientInfoBuilder
from server.application.connection.connection_service import WebConnectionService
from server.models.session_info import SessionInfo
from server.application.connection.recent_device_store import RecentDeviceStore
from server.persistence.rch_database import RchDatabase


def test_linux_dmi_codes_and_cloud_unknown(monkeypatch):
    monkeypatch.setattr(chassis.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(chassis, '_read', lambda _: '1')
    monkeypatch.setattr(chassis, '_run', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('Linux cannot spawn a subprocess')))
    assert chassis._detect_chassis_type() == 'unknown'
    for code, expected in [('17', 'server'), ('23', 'server'), ('9', 'laptop'), ('3', 'desktop'), ('30', 'tablet'), ('', 'unknown'), ('2', 'unknown')]:
        monkeypatch.setattr(chassis, '_read', lambda _, code=code: code)
        assert chassis._detect_chassis_type() == expected


def test_windows_powershell_uses_original_cim_class_and_bounded_probe(monkeypatch):
    monkeypatch.setattr(chassis.platform, 'system', lambda: 'Windows')
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return json.dumps({'chassis': [9]})

    monkeypatch.setattr(chassis, '_run', fake_run)
    assert chassis._detect_chassis_type() == 'laptop'
    assert len(calls) == 1
    args, opts = calls[0]
    assert args[0] == 'powershell.exe'
    assert 'Win32_SystemEnclosure' in args[-1]
    assert opts == {}
    monkeypatch.setattr(chassis, '_run', lambda *args, **kwargs: '{"chassis": 17}')
    assert chassis._detect_chassis_type() == 'server'
    monkeypatch.setattr(chassis, '_run', lambda *args, **kwargs: '')
    assert chassis._detect_chassis_type() == 'unknown'


def test_mac_uses_fast_model_before_profiler_fallback(monkeypatch):
    monkeypatch.setattr(chassis.platform, 'system', lambda: 'Darwin')
    calls = []

    def fast_run(*args, **kwargs):
        calls.append(args[0])
        return 'MacBookPro18,2'

    monkeypatch.setattr(chassis, '_run', fast_run)
    assert chassis._detect_chassis_type() == 'laptop'
    assert calls == ['sysctl']

    def fallback_run(*args, **kwargs):
        return 'Mac14,7' if args[0] == 'sysctl' else '{"SPHardwareDataType": [{"machine_name": "Mac mini"}]}'

    monkeypatch.setattr(chassis, '_run', fallback_run)
    assert chassis._detect_chassis_type() == 'desktop'


def test_ios_and_android_form_factors(monkeypatch):
    monkeypatch.setattr(chassis.platform, 'system', lambda: 'iPadOS')
    monkeypatch.setattr(chassis.platform, 'ios_ver', lambda: SimpleNamespace(model='iPad14,5'), raising=False)
    assert chassis._detect_chassis_type() == 'tablet'
    monkeypatch.setattr(chassis.platform, 'ios_ver', lambda: SimpleNamespace(model='iPhone15,2'))
    assert chassis._detect_chassis_type() == 'phone'
    monkeypatch.setattr(chassis.platform, 'system', lambda: 'Android')
    monkeypatch.setattr(chassis, '_run', lambda *a, **k: 'phone,watch')
    assert chassis._detect_chassis_type() == 'phone'


def test_chassis_probe_is_process_cached(monkeypatch):
    chassis.get_chassis_type.cache_clear()
    calls = []
    monkeypatch.setattr(chassis, '_detect_chassis_type', lambda: calls.append(1) or 'server')
    try:
        assert chassis.get_chassis_type() == 'server'
        assert chassis.get_chassis_type() == 'server'
        assert len(calls) == 1
    finally:
        chassis.get_chassis_type.cache_clear()


def test_handshake_and_variable_use_same_cached_value(monkeypatch):
    monkeypatch.setattr(builder_module, 'get_chassis_type', lambda: 'laptop')
    monkeypatch.setattr(variable_module, 'get_chassis_type', lambda: 'laptop')
    identity = SimpleNamespace(os_alias='linux', os_type='Linux', os_full='Linux', os_name='Linux',
        os_version='test', arch='x86_64', manufacturer='vendor', model='model', hostname='host',
        machine_id='machine', fingerprint_basis='basis')
    monkeypatch.setattr(builder_module, 'get_local_identity', lambda: identity)
    monkeypatch.setattr(builder_module, '_get_client_revision_manifest', lambda: {'revision': '', 'files': {}})
    monkeypatch.setattr(ClientInfoBuilder, '_get_launch_context', classmethod(lambda cls, _: {'mode': 'terminal', 'source': 'sh'}))
    monkeypatch.setattr(ClientInfoBuilder, '_build_process_info', lambda self, _: {'username': 'user', 'process_name': 'python'})
    monkeypatch.setattr(builder_module, 'check_privilege', lambda: 'User')
    monkeypatch.setattr(builder_module, 'get_executable_path', lambda: '/usr/bin/python')
    monkeypatch.setattr(builder_module, 'get_system_paths', lambda: {})
    monkeypatch.setattr(builder_module, 'get_client_log_path', lambda: '')

    resolver = CommandVariableResolver(SimpleNamespace(client_id='client-id'))
    manifest = resolver.get_manifest_payload()
    assert any(item['template'] == '${rch:chassis_type}' for item in manifest)
    assert resolver.resolve('${rch:chassis_type}') == 'laptop'
    builder = ClientInfoBuilder('client-id', command_executor=SimpleNamespace(
        get_commands=lambda: SimpleNamespace(get_command_manifest_payload=lambda: []),
        get_command_variable_manifest=resolver.get_manifest_payload,
    ), features={})
    payload = builder.build()
    assert payload['chassis_type'] == 'laptop'
    assert any(item['name'] == 'chassis_type' for item in payload['variable_manifest'])

    session_info = SessionInfo.from_dict(payload)
    assert session_info.chassis_type == 'laptop'
    assert session_info.to_dict()['chassis_type'] == 'laptop'
    context = SimpleNamespace(
        connected_at='', disconnected_at='', last_seen_at='',
        last_heartbeat_sent_at='', last_heartbeat_ack_at='', last_rtt_ms=None,
    )
    service = WebConnectionService(SimpleNamespace(), None, None)
    summary = service.serialize_connection(SimpleNamespace(session_info=session_info, context=context))
    assert summary['chassis_type'] == 'laptop'


def test_missing_chassis_defaults_to_unknown():
    assert SessionInfo.from_dict({'id': 'go-client'}).chassis_type == 'unknown'


def test_recent_device_chassis_survives_offline_snapshot(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    try:
        recent = RecentDeviceStore(database)
        online = {
            'machine_id': 'machine-1', 'client_id': 'client-1',
            'hostname': 'host', 'chassis_type': 'server',
            'connection_state': 'online',
        }
        recent.upsert_from_connection(online)
        records = recent.list_recent_devices()
        assert len(records) == 1
        assert records[0]['chassis_type'] == 'server'

        service = WebConnectionService(SimpleNamespace(), None, None, recent_device_store=recent)
        entries = service._build_recent_offline_entries([])
        assert len(entries) == 1
        assert entries[0]['chassis_type'] == 'server'
    finally:
        database.close_thread_connection()


def test_probe_timeout_returns_unknown_with_three_second_limit(monkeypatch):
    monkeypatch.setattr(chassis.platform, 'system', lambda: 'Windows')
    observed = []

    def timed_out(*args, **kwargs):
        observed.append(kwargs['timeout'])
        raise subprocess.TimeoutExpired(args[0], kwargs['timeout'])

    import subprocess
    monkeypatch.setattr(chassis.subprocess, 'run', timed_out)
    assert chassis._detect_chassis_type() == 'unknown'
    assert observed == [3]


def test_chassis_codes_match_standalone_recon_script():
    script_path = Path(__file__).resolve().parents[1] / 'server/resources/scripts/common/recon/detect_device.py'
    script_namespace = runpy.run_path(str(script_path), run_name='rch_recon_test')
    assert script_namespace['CHASSIS_TYPES'] == chassis.CHASSIS_TYPES
    assert script_namespace['chassis_type']([1]) == 'unknown'
    assert script_namespace['chassis_type']([17]) == 'server'
