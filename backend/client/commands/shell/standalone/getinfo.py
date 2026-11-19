"""Get system information with an explicit default/full field policy."""

import os
import platform
import shlex
import subprocess
import time

from client.commands.runtime.interrupts import timeout
from client.runtime.client_util import get_executable_path
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.commands.shell.decorators import shell_command
from client.commands.shell.standalone.getinfo_collectors import (
    COLLECTORS, _optional, _text, _size, _duration,
)
from core.device.apple_models import resolve_apple_model_name, resolve_macos_product
from core.device.local_identity import get_local_identity
from core.utils.command_output import StructuredCommandResult
from core.utils.formatting import timestamp_to_readable_time


# Selection belongs here, not in shared collectors or formatting infrastructure.
CORE_FIELDS = (
    'os_name', 'os_version', 'arch', 'manufacturer', 'model', 'hostname',
    'cpu_model', 'cpu_count', 'mem_total', 'mem_avail',
    'pid', 'ppid', 'process_name', 'username', 'python_version',
    'system_uptime', 'process_uptime', 'kernel',
    'rch_build_ver', 'rch_build_revision',
)
CORE_DETAIL_FIELDS = (
    'os_product', 'os_build', 'gpu_models', 'launch_command',
    'system_boot_time', 'process_start_time',
)
PLATFORM_FIELDS = {
    'mac': ('default_shell', 'default_shell_version'),
    'win': ('integrity',),
    'linux': ('default_shell', 'default_shell_version'),
    'ios': ('device_name', 'device_model', 'device_type', 'app_name', 'bundle_identifier'),
}
PLATFORM_DETAIL_FIELDS = {
    'mac': (),
    'win': ('locale', 'user_sid', 'group_sid'),
    'linux': (),
    'ios': (
        'machine_name', 'identifier_for_vendor', 'bundle_path',
        'bundle_executable_path', 'bundle_name', 'bundle_version',
        'bundle_short_version', 'low_power_mode_enabled',
        'home', 'documents', 'temp', 'icloud',
    ),
}



def _process_launch_command(process):
    args = process.cmdline()
    if not args:
        return None
    return subprocess.list2cmdline(args) if os.name == 'nt' else shlex.join(args)



def _base_os_product(identity):
    version = _text(identity.os_version)
    if identity.os_alias == 'mac':
        return resolve_macos_product(version)
    if identity.os_alias == 'ios':
        return f'iOS {version}' if version else 'iOS'
    return None



def _client_build():
    """Use the same build values as the client handshake, including bundled revision."""
    from client.config.config import CLIENT_BUILD_VERSION
    from client.connection.handshake import _get_client_revision_manifest
    return CLIENT_BUILD_VERSION, _get_client_revision_manifest().get('revision') or None



def _core_snapshot(identity, *, detailed):
    """Shared identity and process fields; never invoke deep collectors here."""
    now = time.time()
    build_ver, revision = _client_build()
    values = {
        'os_name': _text(identity.os_name),
        'os_version': _text(identity.os_version),
        'arch': _text(identity.arch),
        'manufacturer': _text(identity.manufacturer),
        'model': (resolve_apple_model_name(identity.model)
                  if identity.os_alias in ('mac', 'ios') else _text(identity.model)),
        'hostname': _text(identity.hostname),
        'cpu_count': _optional(os.cpu_count),
        'pid': os.getpid(),
        'ppid': _optional(os.getppid),
        'python_version': platform.python_version(),
        'kernel': _text(platform.release()),
        'rch_build_ver': _text(build_ver),
        'rch_build_revision': _text(revision),
    }
    if detailed:
        values['os_product'] = _base_os_product(identity)
        values['launch_command'] = _optional(get_executable_path)
    if identity.os_alias != 'ios':
        import psutil
        memory = _optional(psutil.virtual_memory)
        process = _optional(psutil.Process)
        values.update({
            'username': _optional(process.username) if process is not None else None,
            'process_name': _optional(process.name) if process is not None else None,
            'mem_total': _size(memory.total) if memory is not None else None,
            'mem_avail': _size(memory.available) if memory is not None else None,
        })
        boot = _optional(psutil.boot_time)
        start = _optional(process.create_time) if process is not None else None
        values['system_uptime'] = _duration(now - boot) if boot is not None else None
        values['process_uptime'] = _duration(now - start) if start is not None else None
        if detailed:
            values.update({
                'system_boot_time': timestamp_to_readable_time(boot) if boot is not None else None,
                'process_start_time': timestamp_to_readable_time(start) if start is not None else None,
            })
            if process is not None:
                values['launch_command'] = (
                    _optional(lambda: _process_launch_command(process)) or values['launch_command']
                )
    return values



def _selected_fields(alias, *, detailed):
    fields = CORE_FIELDS + (CORE_DETAIL_FIELDS if detailed else ())
    fields += PLATFORM_FIELDS[alias]
    if detailed:
        fields += PLATFORM_DETAIL_FIELDS[alias]
    return fields



@shell_command('Get system information', group='system')
@timeout(30)
def getinfo(self, arg=''):
    """Return the fast snapshot or expanded diagnostics; --json selects rendering."""
    flags = str(arg or '').strip().split()
    if any(flag not in ('json', '--json', '-a', '--all') for flag in flags):
        return 0, 'Usage: getinfo [-a|--all] [--json]'
    detailed = '-a' in flags or '--all' in flags
    try:
        identity = get_local_identity()
        self._checkpoint()
        snapshot = _core_snapshot(identity, detailed=detailed)
        snapshot.update(COLLECTORS[identity.os_alias](self, detailed=detailed))
        # Exactly one field policy controls text and JSON output; expensive probes
        # are guarded inside their platform collectors, not merely hidden here.
        fields = _selected_fields(identity.os_alias, detailed=detailed)
        data = {key: snapshot.get(key) for key in fields}
        return StructuredCommandResult(status=1, data=data, shape='dict', width=24, null_text='N/A')
    except (CommandCancelledError, CommandTimeoutError):
        raise
    except Exception as exc:
        return 0, f'Failed to collect system information: {exc}'

