"""Independent Client process-death supervisor (not a heartbeat watchdog)."""

import json
import logging
from logging.handlers import RotatingFileHandler
import os
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

import psutil

from client.watchdog.watchdog_paths import get_watchdog_log_path
from client.watchdog.recovery_source import RECOVERY_SOURCE_ENV, PROCESS_WATCHDOG


_ENV_SESSION = 'RCH_PROCESS_WATCHDOG_SESSION'
_ENV_PID = 'RCH_PROCESS_WATCHDOG_PID'
_ENV_STARTED = 'RCH_PROCESS_WATCHDOG_STARTED'
_ENV_KEYS = (_ENV_SESSION, _ENV_PID, _ENV_STARTED)
_POLL_INTERVAL = 0.5
_STOP_TIMEOUT = 3.0
_RETRY_DELAYS = (3, 10, 30, 60, 120, 300)
_STABLE_SECONDS = 300


def without_process_watchdog_environment(source=None):
    """A separately launched Client must receive a NEW supervisor chain."""
    env = dict(os.environ if source is None else source)
    for key in (*_ENV_KEYS, RECOVERY_SOURCE_ENV):
        env.pop(key, None)
    return env


def _process_identity(pid):
    try:
        process = psutil.Process(int(pid))
        # psutil 7.2.2 uses monotonic process start time in _ident on macOS/Linux.
        # Unlike create_time(), it cannot shift when NTP adjusts the system clock.
        identity = process._ident[1]
        return identity if identity else None
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, OverflowError, OSError):
        return None


def _probe_process(pid, started):
    """Return (alive, reason); uncertain reads never prove a Client is dead."""
    try:
        pid = int(pid)
        if pid <= 0:
            return False, 'invalid watched PID'
        process = psutil.Process(pid)
        identity = process._ident[1]
        if started and identity and identity != float(started):
            return False, f'PID identity changed: expected={started!r}, actual={identity!r}'
        if not process.is_running():
            return False, 'PID not running or reused'
        if process.status() == psutil.STATUS_ZOMBIE:
            return False, 'PID is zombie'
        if not started or not identity:
            return True, 'PID alive; identity temporarily unavailable'
        return True, 'PID alive with matching identity'
    except psutil.NoSuchProcess:
        return False, 'PID no longer exists'
    except (ValueError, OverflowError):
        return False, 'invalid watched PID'
    except (psutil.AccessDenied, OSError) as exc:
        return True, f'PID probe uncertain ({type(exc).__name__})'


def _alive(pid, started):
    return _probe_process(pid, started)[0]

def _atomic_json(path, payload):
    temp_path = f'{path}.{os.getpid()}.tmp'
    with open(temp_path, 'w', encoding='utf-8') as file_obj:
        json.dump(payload, file_obj)
    os.replace(temp_path, path)


def _logger():
    path = get_watchdog_log_path('process_watchdog.log')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    logger = logging.getLogger('rch_process_watchdog')
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = RotatingFileHandler(path, maxBytes=2 * 1024 * 1024, backupCount=2, encoding='utf-8')
        handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s'))
        logger.addHandler(handler)
    return logger


def _worker_command(session, parent_pid, parent_started, launch_argv, cwd):
    executable = os.path.realpath(sys.executable)
    prefix = [executable] if getattr(sys, 'frozen', False) else [executable, os.path.realpath(sys.argv[0])]
    return [*prefix, '--process-watchdog-worker', '--process-watchdog-session', session,
            '--process-watchdog-parent-pid', str(parent_pid),
            '--process-watchdog-parent-started', repr(parent_started),
            '--process-watchdog-launch-json', json.dumps(launch_argv),
            '--process-watchdog-cwd', cwd]


def _launch_argv():
    executable = os.path.realpath(sys.executable)
    if getattr(sys, 'frozen', False):
        return [executable, *sys.argv[1:]]
    return [executable, os.path.realpath(sys.argv[0]), *sys.argv[1:]]


def _detached_kwargs(cwd, env):
    kwargs = dict(cwd=cwd, env=env, shell=False, stdin=subprocess.DEVNULL,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    if os.name == 'nt':
        kwargs['creationflags'] = (getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
                                   | getattr(subprocess, 'DETACHED_PROCESS', 0))
    elif os.name == 'posix':
        kwargs['start_new_session'] = True
    else:
        raise RuntimeError(f'Unsupported platform: {os.name}')
    return kwargs


def _session_from_environment():
    session = os.environ.get(_ENV_SESSION, '')
    pid_text = os.environ.get(_ENV_PID, '')
    started_text = os.environ.get(_ENV_STARTED, '')
    try:
        pid = int(pid_text)
        started = float(started_text)
    except ValueError:
        return ''
    if session and os.path.isdir(session) and _alive(pid, started):
        return session
    return ''


def stop_process_watchdog_from_environment():
    """Used by the separate Remote/Local HTTP watchdog before deliberate kill/relaunch."""
    session = _session_from_environment()
    if not session:
        return True
    if _request_stop(session):
        return True
    try:
        pid = int(os.environ[_ENV_PID])
        started = float(os.environ[_ENV_STARTED])
        if _alive(pid, started):
            psutil.Process(pid).terminate()
            psutil.Process(pid).wait(timeout=2)
    except (ValueError, KeyError, psutil.Error, OSError):
        return False
    return True


def _request_stop(session):
    stop_path = os.path.join(session, 'stop')
    ack_path = os.path.join(session, 'stopped')
    try:
        _atomic_json(stop_path, {'pid': os.getpid(), 'intent': 'stop'})
    except OSError:
        return False
    deadline = time.monotonic() + _STOP_TIMEOUT
    while time.monotonic() < deadline:
        if os.path.isfile(ack_path) or not os.path.isdir(session):
            return True
        time.sleep(0.05)
    return False


def get_process_watchdog_status_payload(manager=None):
    """Report process-death supervision separately from Remote/Local heartbeat workers."""
    from client.config import runtime_config

    pid = getattr(manager, 'supervisor_pid', None)
    started = getattr(manager, 'supervisor_started', None)
    return {
        'enabled': bool(runtime_config.PROCESS_WATCHDOG_ENABLED),
        'supervisor_pid': pid,
        'supervisor_alive': bool(pid is not None and started is not None and _alive(pid, started)),
        'poll_interval_seconds': _POLL_INTERVAL,
        'log_path': get_watchdog_log_path('process_watchdog.log'),
    }


class ProcessWatchdogManager:
    """Client-side control endpoint; the monitor itself runs in a detached process."""

    def __init__(self):
        self.session = ''
        self.supervisor_pid = None
        self.supervisor_started = None

    def start(self):
        if self.session and self.supervisor_pid and _alive(self.supervisor_pid, self.supervisor_started):
            return
        inherited = _session_from_environment()
        if inherited:
            self.session = inherited
            self.supervisor_pid = int(os.environ[_ENV_PID])
            self.supervisor_started = float(os.environ[_ENV_STARTED])
            return

        # Stale inheritance must never be copied into a fresh supervisor.
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        session = tempfile.mkdtemp(prefix='rch_process_watchdog_')
        parent_started = _process_identity(os.getpid())
        if parent_started is None:
            shutil.rmtree(session, ignore_errors=True)
            raise RuntimeError('Cannot identify Client PID for process supervision')
        try:
            process = subprocess.Popen(
                _worker_command(session, os.getpid(), parent_started, _launch_argv(), os.getcwd()),
                **_detached_kwargs(os.getcwd(), without_process_watchdog_environment()),
            )
            ready_path = os.path.join(session, 'ready.json')
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if os.path.isfile(ready_path):
                    with open(ready_path, 'r', encoding='utf-8') as file_obj:
                        ready = json.load(file_obj)
                    if int(ready['pid']) != process.pid:
                        raise RuntimeError('Process watchdog identity mismatch')
                    self.session = session
                    self.supervisor_pid = process.pid
                    self.supervisor_started = float(ready['started'])
                    os.environ[_ENV_SESSION] = session
                    os.environ[_ENV_PID] = str(self.supervisor_pid)
                    os.environ[_ENV_STARTED] = repr(self.supervisor_started)
                    return
                if process.poll() is not None:
                    raise RuntimeError(f'Process watchdog worker exited: {process.returncode}')
                time.sleep(0.05)
            raise RuntimeError('Process watchdog worker did not become ready')
        except Exception:
            # Never leave an untracked supervisor alive after a failed startup handshake.
            if 'process' in locals() and process.poll() is None:
                process.terminate()
            shutil.rmtree(session, ignore_errors=True)
            raise

    def stop(self):
        session = self.session or _session_from_environment()
        ok = True
        if session:
            ok = _request_stop(session)
            if not ok and self.supervisor_pid and _alive(self.supervisor_pid, self.supervisor_started):
                # A deliberate shutdown must not be countermanded by a wedged supervisor.
                try:
                    psutil.Process(self.supervisor_pid).terminate()
                    psutil.Process(self.supervisor_pid).wait(timeout=2)
                    ok = True
                except (psutil.Error, OSError):
                    pass
        self.session = ''
        self.supervisor_pid = None
        self.supervisor_started = None
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        return ok


def run_process_watchdog_worker_from_argv():
    args = sys.argv

    def value(flag):
        index = args.index(flag)
        return args[index + 1]

    session = value('--process-watchdog-session')
    parent_pid = int(value('--process-watchdog-parent-pid'))
    parent_started = float(value('--process-watchdog-parent-started'))
    launch_argv = json.loads(value('--process-watchdog-launch-json'))
    cwd = value('--process-watchdog-cwd')
    if not isinstance(launch_argv, list) or not launch_argv or not all(isinstance(x, str) for x in launch_argv):
        raise ValueError('Invalid Client launch argv')
    run_process_supervisor(session, parent_pid, parent_started, launch_argv, cwd)


def run_process_supervisor(session, parent_pid, parent_started, launch_argv, cwd):
    log = _logger()
    supervisor_pid = os.getpid()
    supervisor_started = _process_identity(supervisor_pid)
    if supervisor_started is None:
        raise RuntimeError('Cannot identify process supervisor')
    _atomic_json(os.path.join(session, 'ready.json'),
                 {'pid': supervisor_pid, 'started': supervisor_started})
    log.info('watching Client pid=%s, supervisor pid=%s', parent_pid, supervisor_pid)

    child = None
    watched_pid, watched_started = parent_pid, parent_started
    running_since = time.monotonic()
    failures = 0
    try:
        while True:
            if os.path.exists(os.path.join(session, 'stop')):
                _atomic_json(os.path.join(session, 'stopped'), {'pid': supervisor_pid})
                log.info('intentional stop, watched Client pid=%s', watched_pid)
                return
            if watched_started is None and child is not None and child.pid == watched_pid:
                # A just-spawned child can be briefly unqueryable. Only adopt its
                # identity while the Popen handle still identifies a live child.
                if child.poll() is None:
                    watched_started = _process_identity(watched_pid)
            if _alive(watched_pid, watched_started):
                time.sleep(_POLL_INTERVAL)
                continue
            alive, reason = _probe_process(watched_pid, watched_started)
            if alive:
                # A failed probe must be reproducible before beginning recovery.
                time.sleep(_POLL_INTERVAL)
                continue
            uptime = time.monotonic() - running_since
            next_failures = 1 if uptime >= _STABLE_SECONDS else failures + 1
            delay = _RETRY_DELAYS[min(next_failures - 1, len(_RETRY_DELAYS) - 1)]
            log.warning('Client pid=%s appears gone (%s) after %.1fs; verify again in %ss (failure %s)',
                        watched_pid, reason, uptime, delay, next_failures)
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                if os.path.exists(os.path.join(session, 'stop')):
                    _atomic_json(os.path.join(session, 'stopped'), {'pid': supervisor_pid})
                    return
                time.sleep(min(_POLL_INTERVAL, deadline - time.monotonic()))
            if os.path.exists(os.path.join(session, 'stop')):
                _atomic_json(os.path.join(session, 'stopped'), {'pid': supervisor_pid})
                return
            if _alive(watched_pid, watched_started):
                log.info('Client pid=%s still alive on final check; restart cancelled', watched_pid)
                continue
            if child is not None:
                child.poll()  # Reap the last subprocess; avoid accumulating zombies.
            failures = next_failures
            env = without_process_watchdog_environment()
            env.update({_ENV_SESSION: session, _ENV_PID: str(supervisor_pid),
                        _ENV_STARTED: repr(supervisor_started),
                        RECOVERY_SOURCE_ENV: PROCESS_WATCHDOG})
            try:
                child = subprocess.Popen(launch_argv, **_detached_kwargs(cwd, env))
                watched_pid = child.pid
                watched_started = _process_identity(watched_pid)
                if watched_started is None:
                    # An uncertain identity is not proof of death; retry capturing it
                    # while the child is live rather than spawning duplicate Clients.
                    log.warning('started Client pid=%s but its identity is not yet readable', watched_pid)
                running_since = time.monotonic()
                log.info('restarted Client pid=%s', watched_pid)
            except (OSError, ValueError) as exc:
                log.error('failed to restart Client: %s', exc)
                watched_pid, watched_started = 0, 0
                running_since = time.monotonic()
    finally:
        shutil.rmtree(session, ignore_errors=True)
