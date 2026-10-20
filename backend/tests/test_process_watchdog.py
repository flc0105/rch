"""Process-death recovery and intentional lifecycle boundary regression tests."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import psutil

from client.watchdog import process_watchdog as guard
from client.commands.common.mixins.session_ops import CommandSessionMixin
from client.commands.common.mixins.update_ops import CommandUpdateMixin


class ProcessWatchdogLogicTests(unittest.TestCase):
    def test_real_worker_bootstrap_and_chain_adoption(self):
        entrypoint = str(Path(__file__).resolve().parents[1] / 'rchclient.py')
        with patch.object(sys, 'argv', [entrypoint, '--profile', 'dev']):
            primary = guard.ProcessWatchdogManager()
            try:
                primary.start()
                self.assertTrue(psutil.pid_exists(primary.supervisor_pid))
                adopted = guard.ProcessWatchdogManager()
                adopted.start()
                self.assertEqual(adopted.supervisor_pid, primary.supervisor_pid)
                self.assertEqual(adopted.session, primary.session)
            finally:
                self.assertTrue(primary.stop())

    def test_identity_and_wrong_start_time(self):
        pid = os.getpid()
        self.assertTrue(guard._alive(pid, psutil.Process(pid).create_time()))
        self.assertFalse(guard._alive(pid, psutil.Process(pid).create_time() - 1000))
        self.assertFalse(guard._alive(99999999, 0))

    def test_clone_and_update_launches_scrub_supervisor_inheritance(self):
        env = {'RCH_PROCESS_WATCHDOG_SESSION': 'old-session',
               'RCH_PROCESS_WATCHDOG_PID': '30',
               'RCH_PROCESS_WATCHDOG_STARTED': '40', 'PATH': 'safe'}
        self.assertEqual(guard.without_process_watchdog_environment(env), {'PATH': 'safe'})
        self.assertEqual(env['RCH_PROCESS_WATCHDOG_PID'], '30')

    def test_explicit_kill_stops_watchdog_before_sys_exit(self):
        owner = CommandSessionMixin()
        owner.socket = Mock()
        with self.assertRaises(SystemExit) as raised:
            owner.kill_instance()
        self.assertEqual(raised.exception.code, 0)
        owner.socket.process_watchdog_manager.stop.assert_called_once_with()
        owner.socket.close.assert_called_once_with()

    def test_remote_relaunch_stops_supervisor_after_successful_new_spawn(self):
        from client.watchdog.remote_watchdog import WatchdogActionExecutor
        action = WatchdogActionExecutor(os.getpid(), os.getcwd(), ['python', 'dummy'])
        with patch.object(action, 'spawn_restarted_parent') as spawn, \
             patch.object(action, 'kill_parent_process') as kill, \
             patch('client.watchdog.remote_watchdog.stop_process_watchdog_from_environment') as stop, \
             patch('client.watchdog.remote_watchdog.os._exit', side_effect=RuntimeError('intercept')):
            with self.assertRaisesRegex(RuntimeError, 'intercept'):
                action.restart_parent_and_exit()
            spawn.assert_called_once_with()
            stop.assert_called_once_with()
            kill.assert_called_once_with()

    def test_update_candidate_activation_ack(self):
        import rchclient
        with tempfile.TemporaryDirectory() as directory:
            ready = str(Path(directory) / 'ready.json')
            Path(ready + '.accepted').write_text('accepted')
            manager = Mock()
            with patch.object(rchclient.runtime_config, 'PROCESS_WATCHDOG_ENABLED', True):
                rchclient._activate_watchdog_after_update_acceptance(ready, manager)
            manager.start.assert_called_once_with()
            self.assertEqual(json.loads(Path(ready + '.adopted').read_text()), {'ok': True})

    def test_update_activation_rejects_failed_watchdog(self):
        import rchclient
        with tempfile.TemporaryDirectory() as directory:
            ready = str(Path(directory) / 'ready.json')
            Path(ready + '.accepted').write_text('accepted')
            manager = Mock()
            manager.start.side_effect = OSError('watcher failure')
            with patch.object(rchclient.runtime_config, 'PROCESS_WATCHDOG_ENABLED', True):
                rchclient._activate_watchdog_after_update_acceptance(ready, manager)
            result = json.loads(Path(ready + '.adopted').read_text())
            self.assertFalse(result['ok'])
            self.assertIn('watcher failure', result['error'])

    def test_update_accepted_acknowledgement_does_not_require_heartbeat(self):
        owner = CommandUpdateMixin()
        owner._checkpoint = lambda: None
        process = Mock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory:
            ready = str(Path(directory) / 'ready')
            adopted = Path(ready + '.adopted')
            adopted.write_text('{"ok": true}')
            owner._activate_updated_client_watchdog(process, ready)
            self.assertTrue(Path(ready + '.accepted').exists())


class ProcessWatchdogSubprocessTests(unittest.TestCase):
    def test_actual_process_death_restarts_and_intentional_stop_quiesces(self):
        """Real subprocesses, not mocked PIDs: two successive crashes and stop."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            client_script = base / 'client.py'
            process_log = base / 'client_pids.txt'
            client_script.write_text(
                'import os, sys, time\n'
                'with open(sys.argv[1], "a") as file:\n'
                '    file.write(str(os.getpid())+"\\n")\n'
                '    file.flush()\n'
                'if len(open(sys.argv[1]).read().splitlines()) > 1:\n'
                '    time.sleep(60)\n', encoding='utf-8')
            session = str(base / 'session')
            Path(session).mkdir()
            launch = [sys.executable, str(client_script), str(process_log)]
            runner = (
                'import json; import client.watchdog.process_watchdog as w; '
                'w._RETRY_DELAYS=(0.1,); '
                'w.run_process_supervisor(' + repr(session) + ', 99999999, 0, '
                + repr(launch) + ', ' + repr(directory) + ')'
            )
            env = dict(os.environ)
            env['XDG_CONFIG_HOME'] = str(base / 'config')
            env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
            supervisor = subprocess.Popen([sys.executable, '-c', runner], env=env,
                                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.PIPE, text=True)
            spawned = []
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if process_log.exists():
                        spawned = [int(pid) for pid in process_log.read_text().splitlines()]
                        if len(spawned) >= 2:
                            break
                    if supervisor.poll() is not None:
                        self.fail(f'Supervisor exited prematurely: {supervisor.stderr.read()}')
                    time.sleep(0.05)
                self.assertGreaterEqual(len(spawned), 2, 'Client was not restarted after first exit')
                self.assertNotEqual(spawned[0], spawned[1])
                self.assertTrue(psutil.pid_exists(spawned[1]))
                Path(session, 'stop').write_text('{}')
                supervisor.wait(timeout=6)
                self.assertEqual(supervisor.returncode, 0)
                self.assertFalse(Path(session).exists())
                self.assertEqual(len(process_log.read_text().splitlines()), 2)
            finally:
                if supervisor.poll() is None:
                    supervisor.kill()
                    supervisor.wait(timeout=5)
                for pid in spawned:
                    try:
                        psutil.Process(pid).terminate()
                    except psutil.Error:
                        pass


if __name__ == '__main__':
    unittest.main()
