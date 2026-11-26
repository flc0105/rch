"""Build, verify and hand off a Client source bundle."""
import json
import os
import shlex
import threading
from uuid import uuid4

from client.commands.runtime.interrupts import cancel_policy
from client.commands.shell.decorators import shell_command
from client.config.config import RUNTIME_CONFIG
from client.runtime.client_util import (
    get_executable_argv, spawn_detached_python_script,
)
from client.runtime.launch_context import detect_launch_context
from client.app.logging import get_client_log_path
from client.runtime.temp_workspace import get_temp_category_dir, make_client_startup_log
from client.update.preparation import UpdatePreparation, build_request, publish_archive
from client.update.signals import SignalListener, candidate_environment
from core.device.local_identity import get_local_identity
from core.protocol.references import log_file_reference, session_action_reference


def _parse_update_options(arg=''):
    tokens = shlex.split(str(arg or ''))
    if tokens not in ([], ['--observe']):
        raise ValueError('Usage: update [--observe]')
    return {'observe': bool(tokens)}


def _build_update_request_payload():
    return build_request(RUNTIME_CONFIG)


def _extract_update_bundle_safely(archive_path, extract_dir):
    return publish_archive(archive_path, extract_dir)


def _current_revision():
    from client.connection.handshake import _get_client_revision_manifest
    return _get_client_revision_manifest()['revision']


def _expected_revision(script):
    profile = os.path.join(os.path.dirname(script), 'client', 'config', 'profiles', 'agent.json')
    with open(profile, encoding='utf-8') as handle:
        result = str(json.load(handle).get('client_source_revision') or '').strip()
    if not result:
        raise ValueError('Built Client bundle lacks its source Revision')
    return result


def _stop_failed_candidate(process):
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=3)
    except Exception:
        try:
            process.kill()
        except OSError:
            pass


def _schedule_exit_after_update(socket, execution_context):
    """End the Client once the Update result has been sent to Server."""
    def exit_client():
        recovery = getattr(socket, 'process_recovery_watchdog_manager', None)
        if recovery is not None:
            recovery.stop()
        watchdog = getattr(socket, 'watchdog_manager', None)
        if watchdog is not None:
            watchdog.stop()
        try:
            socket.report_session_end('client_update', command='update')
            socket.close()
        finally:
            os._exit(0)

    def after_command_finished(_state):
        threading.Thread(target=exit_client, name='ClientUpdateExit', daemon=True).start()

    execution_context.on_completion(after_command_finished)


def _get_update_owner():
    alias = get_local_identity().os_alias
    context = detect_launch_context(alias)
    source = context.get('source', '')
    if source in ('systemd', 'systemd_user', 'windows_service', 'schtasks'):
        raise RuntimeError('Automatic Update for systemd/Windows managed services is not supported yet')
    if source in ('launchagent', 'launchdaemon') and not context.get('service_target'):
        raise RuntimeError('Cannot verify the owning launchd job for Update')
    if alias not in ('mac', 'linux', 'win', 'ios'):
        raise RuntimeError(f'Unsupported Update platform: {alias}')
    return alias, context


@shell_command('Build, download, extract and launch the latest client bundle', group='maintenance', output='stream')
@cancel_policy('cooperative')
def update(self, arg=''):
    process = None
    mode = ''
    managed = False
    observe_log = ''
    try:
        options = _parse_update_options(arg)
        mode = str(RUNTIME_CONFIG.get('connection_mode') or 'reverse').strip()
        if mode not in ('reverse', 'bind'):
            raise ValueError(f'Unsupported connection mode: {mode}')
        alias, context = _get_update_owner()
        managed = context.get('source') in ('launchagent', 'launchdaemon')
        if options['observe'] and (mode != 'reverse' or managed or alias == 'ios'):
            raise ValueError('--observe only supports ordinary desktop Reverse processes')

        script = UpdatePreparation(self).run()
        if alias == 'ios':
            self.emit_completed(status='success', message=(
                f'iOS detected, please restart Pythonista app and manually run script: {script}'
            ))
            return
        revision = _expected_revision(script)
        if mode == 'bind':
            from client.connection.bind_listener import current_bind_listener
            listener = current_bind_listener()
            if listener is None or listener._socket is None:
                raise RuntimeError('This Bind Client does not own an active listening socket')
            with open(os.path.join(os.path.dirname(script), 'client', 'config', 'profiles', 'agent.json'),
                      encoding='utf-8') as handle:
                built_config = json.load(handle)
            if (built_config.get('connection_mode') != 'bind'
                    or (built_config.get('bind_host'), built_config.get('bind_port')) != listener.address):
                raise ValueError('Built Bind configuration does not match the current listener')
        attempt = uuid4().hex

        if mode == 'reverse' and not managed:
            if options['observe']:
                observe_log = make_client_startup_log(prefix='update-')
            with SignalListener() as signal:
                process = spawn_detached_python_script(
                    script, cwd=os.path.dirname(script),
                    env_overrides=candidate_environment(signal.port, signal.secret, attempt),
                    **({'output_path': observe_log} if observe_log else {}),
                )
                packet = signal.accept(
                    attempt_id=attempt, process=process, revision=revision,
                    mode='reverse', timeout=45, checkpoint=self._checkpoint,
                )
            result = f'Updated Client registered with Server: PID {process.pid}, Client ID {packet["client_id"]}'
            if options['observe']:
                self.emit_completed(
                    status='success',
                    message=f'{result}. Verify the new Client before ending this instance.',
                    references=[log_file_reference(observe_log, title='Client update'),
                                session_action_reference('kill_instance')],
                )
            else:
                self.emit_completed(status='success', message=f'{result}. Old Client will exit.')
                _schedule_exit_after_update(self.socket, self.execution_context)
            return

        # Bind cannot listen on the same port while the original Client is running.
        # launchd owns the lifecycle of either mode of its managed job.
        from client.update.handoff import spawn_handoff
        parent_log_dir = os.path.dirname(get_client_log_path()) or get_temp_category_dir('client_logs', private=True)
        log_path = os.path.join(parent_log_dir, f'update_handoff_{attempt}.log')
        plan = dict(
            attempt=attempt, mode=mode, old_pid=os.getpid(),
            candidate_script=script, revision=revision,
            previous_argv=get_executable_argv(), previous_cwd=os.getcwd(),
            previous_revision=_current_revision() if mode == 'bind' else '',
            launchd=context if managed else None,
        )
        process = spawn_handoff(plan, log_path=log_path)
        self.emit_completed(status='success', message=(
            f'Updated Bundle prepared; replacement handoff started (PID {process.pid}). '
            f'Check local handoff log: {log_path}. '
            + ('Reconnect this Bind Client manually from Server after replacement.'
               if mode == 'bind' else 'launchd will restart and verify the Reverse connection.')
        ))
        if not managed:
            _schedule_exit_after_update(self.socket, self.execution_context)
    except Exception as exc:
        if process is not None and process.poll() is None and (mode == 'reverse' and not managed):
            _stop_failed_candidate(process)
        if observe_log:
            self.emit_completed(
                status='error',
                message=f'Failed to update Client bundle: {exc}. Original Client remains online.',
                references=[log_file_reference(observe_log, title='Client update')],
            )
        else:
            self.emit_completed(status='error', message=f'Failed to update Client bundle: {exc}')
