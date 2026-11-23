"""Short-lived Update handoff after a Bind or managed Client releases its port."""
import json
import os
import subprocess
import sys
import time
import traceback

from client.runtime.client_util import is_process_alive, spawn_detached_python_script
from client.update.signals import SignalListener, candidate_environment


class ServiceProcess:
    """Observe the actual PID owned by an already verified launchd job."""
    def __init__(self, manager, pid):
        self.manager = manager
        self.pid = int(pid)

    def poll(self):
        status = self.manager.status()
        if status.get('pid') == self.pid and status.get('running'):
            return None
        return 1


def _still_running(pid):
    if not is_process_alive(pid):
        return False
    if os.name == 'posix':
        import psutil
        try:
            return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            return True
    return True


def wait_for_old_process(pid, timeout=20):
    deadline = time.monotonic() + timeout
    while _still_running(pid):
        if time.monotonic() >= deadline:
            raise TimeoutError('Previous Client did not exit before the Bind handoff')
        time.sleep(.1)


def _start_previous(plan, *, environment=None, output_path=''):
    """Restore the original runtime command; never update the old Release in place."""
    from client.watchdog.watchdog_environment import without_process_recovery_watchdog_environment
    args = list(plan['previous_argv'])
    env = without_process_recovery_watchdog_environment()
    if environment:
        env.update(environment)
    output_file = open(output_path, 'ab') if output_path else None
    kwargs = dict(cwd=plan['previous_cwd'], env=env,
                  stdin=subprocess.DEVNULL,
                  stdout=output_file or subprocess.DEVNULL,
                  stderr=output_file or subprocess.DEVNULL, close_fds=True)
    if os.name == 'nt':
        kwargs['creationflags'] = (getattr(subprocess, 'DETACHED_PROCESS', 0)
                                   | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
    else:
        kwargs['start_new_session'] = True
    try:
        return subprocess.Popen(args, **kwargs)
    finally:
        if output_file is not None:
            output_file.close()


def _stop_candidate(process):
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        process.kill()
        try:
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass


def run_handoff(plan):
    mode = plan['mode']
    managed = plan.get('launchd')
    process = None
    service = None
    succeeded = False
    try:
        if not managed:
            wait_for_old_process(int(plan['old_pid']))
        with SignalListener() as signal:
            attempt = plan['attempt']
            env = candidate_environment(signal.port, signal.secret, attempt)
            if managed:
                from client.update.launchd_handoff import LaunchdUpdateHandoff
                service = LaunchdUpdateHandoff(managed, plan['candidate_script'], env)
                process = service.activate()
            else:
                process = spawn_detached_python_script(
                    plan['candidate_script'], cwd=os.path.dirname(plan['candidate_script']),
                    env_overrides=env, output_path=plan.get('log_path', ''),
                )
            packet = signal.accept(
                attempt_id=attempt, process=process,
                revision=plan['revision'], mode=mode,
            )
            if service is not None:
                service.finalize()
            succeeded = True
            print(f'Update {mode} ready: PID={process.pid}, Client ID={packet["client_id"]}', flush=True)
    except Exception:
        traceback.print_exc()
        if service is not None:
            try:
                service.rollback()
                print('Launchd service restored to previous Client', flush=True)
            except Exception:
                traceback.print_exc()
        elif not succeeded:
            _stop_candidate(process)
            if not managed and not _still_running(int(plan['old_pid'])):
                recovered = None
                try:
                    with SignalListener() as recovery_signal:
                        recovery_attempt = f'{plan["attempt"]}-recovery'
                        recovered = _start_previous(
                            plan,
                            environment=candidate_environment(
                                recovery_signal.port, recovery_signal.secret, recovery_attempt,
                            ),
                            output_path=plan.get('log_path', ''),
                        )
                        recovered_packet = recovery_signal.accept(
                            attempt_id=recovery_attempt, process=recovered,
                            revision=plan['previous_revision'], mode='bind', timeout=15,
                        )
                    print(f'Previous Client listening again: PID={recovered_packet["pid"]}', flush=True)
                except Exception:
                    print('Previous Client failed to restore listening socket', flush=True)
                    traceback.print_exc()
                    _stop_candidate(recovered)
        raise


def spawn_handoff(plan, *, log_path):
    """Detached from the Client connection that is about to be closed."""
    import subprocess
    from client.runtime.client_util import _resolve_python_command_for_source_bundle, get_runtime_root
    from client.watchdog.watchdog_environment import without_process_recovery_watchdog_environment
    plan = {**plan, 'log_path': log_path}
    args = _resolve_python_command_for_source_bundle() + [
        '-m', 'client.update.handoff', json.dumps(plan, separators=(',', ':')),
    ]
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, 'ab') as log:
        kwargs = dict(cwd=get_runtime_root(), env=without_process_recovery_watchdog_environment(),
                      stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, close_fds=True)
        if os.name == 'nt':
            kwargs['creationflags'] = (getattr(subprocess, 'DETACHED_PROCESS', 0)
                                       | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
        else:
            kwargs['start_new_session'] = True
        return subprocess.Popen(args, **kwargs)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python -m client.update.handoff PLAN_JSON')
    run_handoff(json.loads(sys.argv[1]))
