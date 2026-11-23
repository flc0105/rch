"""Change one verified launchd job to a stable entry and activate its Release."""
import hashlib
import json
import os
import plistlib
import tempfile
import time

from client.runtime.launchd_service_manager import LaunchdServiceManager
from client.runtime.client_util import get_client_bundle_release_dir, _resolve_python_command_for_source_bundle
from client.update.handoff import ServiceProcess


def _atomic_file(path, data, mode):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, staging = tempfile.mkstemp(dir=directory, prefix='.rch-launchd-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(staging, mode)
        os.replace(staging, path)
    finally:
        if os.path.exists(staging):
            os.unlink(staging)


class LaunchdUpdateHandoff:
    def __init__(self, context, candidate_script, signal_environment):
        if context['source'] not in ('launchagent', 'launchdaemon'):
            raise ValueError('Expected an OS-verified launchd Client')
        label = context['service_label']
        kind = 'daemon' if context['source'] == 'launchdaemon' else 'agent'
        scope = context.get('service_scope', 'user')
        self.manager = LaunchdServiceManager(
            kind=kind, label=label, scope=scope,
            target_user=context.get('service_uid') if kind == 'agent' else None,
        )
        if self.manager.target.service_target != context['service_target']:
            raise ValueError('launchd service target identity mismatch')
        self.plist_path = self.manager.target.plist_path
        if os.path.realpath(self.plist_path) != os.path.realpath(context['service_plist']):
            raise ValueError('launchd service definition mismatch')
        with open(self.plist_path, 'rb') as handle:
            self.old_plist = handle.read()
        existing = plistlib.loads(self.old_plist)
        self.old_program = list(existing.get('ProgramArguments') or [])
        if not self.old_program:
            raise ValueError('launchd service has no ProgramArguments')
        root = os.path.dirname(get_client_bundle_release_dir())
        self.launcher_path = os.path.join(root, 'launchd_launcher.py')
        job_key = hashlib.sha256(context['service_target'].encode()).hexdigest()[:20]
        self.state_path = os.path.join(root, 'launchd', f'{job_key}.json')
        self.old_state = None
        if os.path.lexists(self.state_path):
            with open(self.state_path, 'rb') as handle:
                self.old_state = handle.read()
        self.expected_program = [*_resolve_python_command_for_source_bundle(), self.launcher_path, self.state_path]
        self.first_install = self.old_program != self.expected_program
        self.candidate_script = os.path.abspath(candidate_script)
        self.signal_environment = dict(signal_environment)
        self._started = False

    def _install_launcher(self):
        from client.update import launchd_entry
        with open(launchd_entry.__file__, 'rb') as handle:
            contents = handle.read()
        _atomic_file(self.launcher_path, contents, 0o644)

    def _write_state(self, script, *, update_environment=None):
        payload = {'script': script, 'args': [], 'update_environment': update_environment or {}}
        _atomic_file(self.state_path, json.dumps(payload, separators=(',', ':')).encode(), 0o600)

    def activate(self):
        # Fail before stopping the live job if a one-time plist migration
        # cannot be performed by this launchd owner.
        self.manager._require_control_privilege()
        if self.first_install:
            self.manager._require_install_privilege()
        # bootout is required before swapping the existing daemon's entry.
        self.manager.stop()
        self._install_launcher()
        self._write_state(self.candidate_script, update_environment=self.signal_environment)
        if self.first_install:
            definition = plistlib.loads(self.old_plist)
            definition['ProgramArguments'] = self.expected_program
            definition['WorkingDirectory'] = os.path.dirname(self.launcher_path)
            self.manager._write_plist(definition)
        self._started = True
        result = self.manager.start()
        pid = result.get('pid')
        for _ in range(30):
            if pid:
                break
            time.sleep(.1)
            pid = self.manager.status().get('pid')
        if not pid:
            raise RuntimeError('launchd did not start the new Client')
        return ServiceProcess(self.manager, pid)

    def finalize(self):
        # Remove the secret from the durable launchd job configuration.
        self._write_state(self.candidate_script)

    def rollback(self):
        if self._started:
            self.manager.stop()
        if self.old_state is not None:
            _atomic_file(self.state_path, self.old_state, 0o600)
        elif os.path.exists(self.state_path):
            os.unlink(self.state_path)
        if self.first_install:
            _atomic_file(self.plist_path, self.old_plist, 0o644)
        self.manager.start()
