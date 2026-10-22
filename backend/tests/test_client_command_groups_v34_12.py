"""Public Client command renames/groups and internal Server call sites (v34.12)."""

import inspect

import pytest

from client.commands.common.commands import CommonCommands
from client.commands.platform.mac import MacCommands
from client.commands.platform.win import WindowsCommands
from client.commands.platform.ios import iOSCommands
from server.application.execution.remote_execution_service import RemoteExecutionService
from client.commands.platform.specs.common import KILL_ARGUMENT_SPEC
from client.commands.platform.specs.mac import IMAGE_INFO_SPEC


COMMON_GROUPS = {
    'shell': ('cd', 'pwd'),
    'execution': ('shell', 'shell_stream', 'bgrun', 'pyexec', 'pyexec_stream'),
    'file': ('zip_dir', 'unzip'),
    'session': ('kill_instance', 'reexec_instance', 'relaunch_instance', 'spawn_instance'),
    'runtime': ('watchdog', 'set'),
    'maintenance': ('clean', 'update'),
    'transfer': ('download',),
    'automation': ('keyboard_send',),
    'privilege': ('is_elevated',),
    'network': ('ifconfig',),
    'system': ('getuid', 'getpid', 'uptime', 'userenum'),
    'python': ('piplist',),
}

PLATFORM_GROUPS = {
    MacCommands: {
        'file': ('file_shred',),
        'system': ('getinfo', 'idletime'),
        'media': ('screenshot', 'webcam_snap'),
        'privilege': ('run_elevated', 'spawn_elevated_instance'),
    },
    WindowsCommands: {
        'system': ('getinfo', 'idletime'),
        'media': ('screenshot',),
        'privilege': ('run_elevated', 'spawn_elevated_instance'),
        'execution': ('run',),
    },
}

OLD_COMMANDS = {
    'kill_connection', 'reset', 'reexec', 'spawn', 'read', 'pyexec_collect',
    'sudo_run', 'sudo_self', 'runasadmin', 'is_root', 'ip', 'receive_http_upload',
}


def _manifest(class_):
    # Manifest is reflection-derived, so assert against the real output rather than
    # maintaining a test-only hand-authored command registry.
    owner = class_.__new__(class_)
    owner._command_runtime = None
    return {row['name']: row for row in owner.get_command_manifest_payload()}


@pytest.mark.parametrize('cls', [CommonCommands, MacCommands, WindowsCommands])
def test_client_manifest_groups_and_removed_names(cls):
    manifest = _manifest(cls)
    for group, names in COMMON_GROUPS.items():
        for name in names:
            assert manifest[name]['group'] == group, (cls.__name__, name)
    for group, names in PLATFORM_GROUPS.get(cls, {}).items():
        for name in names:
            assert manifest[name]['group'] == group, (cls.__name__, name)
    assert 'receive_file' in manifest
    assert manifest['receive_file']['suggest'] is False
    assert not OLD_COMMANDS.intersection(manifest), OLD_COMMANDS.intersection(manifest)
    assert inspect.signature(getattr(cls, 'bgrun')) == inspect.signature(CommonCommands.bgrun)


def test_ios_only_clipboard_methods_renamed_without_regrouping():
    manifest = _manifest(iOSCommands)
    assert manifest['clipboard_read']['group'] == 'mobile'
    assert manifest['clipboard_write']['group'] == 'mobile'
    assert 'readclip' not in manifest and 'writeclip' not in manifest
    assert manifest['getinfo']['group'] == 'platform'


def test_internal_upload_client_command_uses_renamed_receiver():
    service = RemoteExecutionService.__new__(RemoteExecutionService)
    text = service._build_http_receive_command({'relative_url': '/api/files/x', 'filename': 'x'})
    assert text.startswith('receive_file __json__:')
    assert 'receive_http_upload' not in text


def test_session_methods_are_exported_without_aliases():
    manifest = _manifest(CommonCommands)
    for name in ('kill_instance', 'relaunch_instance', 'reexec_instance', 'spawn_instance'):
        assert manifest[name]['group'] == 'session'
    assert 'reset' not in manifest and 'kill_connection' not in manifest


def test_client_public_descriptions_are_concise_and_platform_consistent():
    common = _manifest(CommonCommands)
    mac = _manifest(MacCommands)
    win = _manifest(WindowsCommands)
    assert common['update']['help'] == 'Build, download, extract and launch the latest client bundle'
    assert common['is_elevated']['help'] == 'Check whether the current process has elevated privileges'
    assert mac['run_elevated']['help'] == win['run_elevated']['help'] == (
        'Run a command with elevated privileges'
    )
    assert mac['spawn_elevated_instance']['help'] == win['spawn_elevated_instance']['help'] == 'Launch a new instance with elevated privileges'
    assert KILL_ARGUMENT_SPEC.description == 'Kill processes'
    assert IMAGE_INFO_SPEC.description == 'Show image metadata'
    # Only the description changes; the option parser and --keep-old behavior remain.
    assert '--keep-old' in inspect.getsource(CommonCommands.update)
