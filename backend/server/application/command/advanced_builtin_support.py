"""New opt-in, preview-gated builtins; ordinary Client process commands remain intact."""
import json
import shlex
import threading
from datetime import datetime

from server.application.command.interaction_builtin_support import BuiltinInteractionError
from server.application.command.process_control_client_source import PROCESS_CONTROL_SOURCE
from server.application.command.command_types import COMMAND_TYPE_SCRIPT


class AdvancedBuiltinSupport:
    def __init__(self, conn, interactions, remote_execution_service):
        self.conn = conn
        self.interactions = interactions
        self.remote = remote_execution_service

    def disconnect(self, arg=''):
        if str(arg or '').strip():
            yield 0, 'Usage: disconnect'
            return
        info = self.conn.session_info
        identity = (f'Client: {getattr(info, "client_id", "")}\n'
                    f'Host: {getattr(info, "hostname", "")}\n'
                    'Action: close the current Server/Client connection (agent may reconnect).')
        yield 1, 'Preview:\n' + identity
        try:
            if not self.interactions.confirm(identity, title='Disconnect this client?'):
                yield 0, 'Disconnect cancelled'
                return
        except BuiltinInteractionError as exc:
            yield 0, f'Disconnect cancelled: {exc}'
            return
        yield 1, 'Disconnect approved; closing this connection.'
        # Let the output event flush before transport teardown.
        worker = threading.Timer(0.35, self.conn.close)
        worker.daemon = True
        worker.start()

    def advanced_demo(self, arg=''):
        if str(arg or '').strip():
            yield 0, 'Usage: interaction_advanced_demo'
            return
        try:
            choice = self.interactions.select('Choose a harmless demo action:',
                                               ['Preview only', 'Execute demo'], title='Select demo mode')
            if choice == 'Preview only':
                yield 1, 'Demo preview only; no operation executed.'
                return
            secret = self.interactions.ask('Enter a secret sample (never printed):',
                                           title='Secret input demo', secret=True)
            if not self.interactions.confirm('Run harmless demo and discard secret?', title='Demo approval'):
                yield 0, 'Demo rejected'
                return
            yield 1, 'Demo complete; secret received but not disclosed.'
        except BuiltinInteractionError as exc:
            yield 0, f'Demo cancelled: {exc}'

    def _remote(self, arguments):
        # Internal Client script executes inside the already acquired foreground task.
        # stream_command intentionally does not request a second (busy) foreground slot.
        chunks = []
        for status, text in self.remote.stream_command(
            self.conn, PROCESS_CONTROL_SOURCE,
            command_type=COMMAND_TYPE_SCRIPT, extra=arguments,
        ):
            text = str(text or '')
            if text.startswith('__RCH_PROCESS_CONTROL_RESULT__:'):
                chunks.append(text.split('__RCH_PROCESS_CONTROL_RESULT__:', 1)[1].strip())
            elif status == 0:
                raise RuntimeError(f'Client process inspection failed: {text[:500]}')
        if not chunks:
            raise RuntimeError('Client returned no process inspection result')
        response = json.loads(chunks[-1])
        if not response.get('ok'):
            raise RuntimeError(response.get('error') or 'Remote process operation failed')
        return response['data']

    @staticmethod
    def _parse_process_args(arg, *, by_port):
        parts = shlex.split(str(arg or ''))
        parsed = {'force': False}
        index = 0
        while index < len(parts):
            token = parts[index]
            if token in ('--force', '-9'):
                parsed['force'] = True
                index += 1
                continue
            if token not in (('--port',) if by_port else ('--pid', '--name')) or index + 1 >= len(parts):
                raise ValueError('Expected --port N or --pid N / --name NAME, optionally --force')
            key = token[2:]
            if key in parsed:
                raise ValueError(f'Duplicate argument: {token}')
            parsed[key] = parts[index + 1]
            index += 2
        if by_port:
            if 'port' not in parsed:
                raise ValueError('Usage: kill_by_port --port PORT [--force]')
            parsed['port'] = int(parsed['port'])
            if not 1 <= parsed['port'] <= 65535:
                raise ValueError('Port must be 1-65535')
        else:
            if not ('pid' in parsed or 'name' in parsed):
                raise ValueError('Usage: kill_process_preview --pid PID [--name NAME] [--force], or --name NAME [--force]')
            if 'pid' in parsed:
                parsed['pid'] = int(parsed['pid'])
                if parsed['pid'] <= 1:
                    raise ValueError('PID must be greater than 1')
        return parsed

    @staticmethod
    def _format_preview(row, force, port=None):
        lines = [
            f'PID: {row["pid"]}', f'Name: {row["name"]}', f'User: {row["user"]}',
            f'Executable: {row["exec_path"]}', f'Command: {row["cmdline"]}',
            f'Working directory: {row["cwd"]}', f'Parent PID: {row["ppid"]}',
            f'Status: {row["status"]}', f'Started (epoch): {row["created_at"]}',
            f'Memory RSS: {row["memory_rss"]} bytes', f'Threads: {row["threads"]}',
            'Listening ports:',
            *[f'  {item["protocol"]} {item["address"]}:{item["port"]}' for item in row['listening']],
            f'Termination: {"SIGKILL (-9)" if force else "SIGTERM (graceful)"}',
        ]
        if port is not None:
            lines.append(f'Port ownership must still match: {port}')
        return '\n'.join(lines)

    def kill(self, arg='', *, by_port=False):
        usage = 'kill_by_port --port PORT [--force]' if by_port else 'kill_process_preview --pid PID [--name NAME] [--force]'
        try:
            text = str(arg or '').strip()
            if not text:
                if by_port:
                    number = self.interactions.ask('Enter a listening TCP/UDP port:', title='Port to inspect')
                    text = f'--port {number}'
                else:
                    kind = self.interactions.select('Search the connected Client by:',
                                                    ['PID', 'Name'], title='Choose process lookup')
                    value = self.interactions.ask(f'Enter {kind}:', title='Process target')
                    # shlex.quote prevents a name from injecting command options.
                    text = f'--{kind.lower()} {shlex.quote(value)}'
            options = self._parse_process_args(text, by_port=by_port)
            rows = self._remote({**options, 'action': 'inspect'}).get('processes', [])
            if not rows:
                raise ValueError('No matching process found on the connected client')
            if len(rows) > 24:
                raise ValueError('Too many matches; narrow the target with --pid')
            if len(rows) > 1:
                labels = [f'{row["pid"]}: {row["name"]} ({row["user"]})' for row in rows]
                selected = self.interactions.select(
                    f'{len(rows)} processes matched. Select exactly one target:', labels,
                    title='Choose process to inspect')
                row = rows[labels.index(selected)]
            else:
                row = rows[0]
            if row['pid'] <= 1:
                raise ValueError('Protected PID')
            preview = self._format_preview(row, options['force'], port=options.get('port'))
            yield 1, 'Process termination preview:\n' + preview
            if not self.interactions.confirm(preview, title='Approve process termination?'):
                yield 0, 'Termination rejected; no signal sent'
                return
            args = {
                'action': 'terminate', 'pid': row['pid'], 'created_at': row['created_at'],
                'expected_name': row['name'], 'expected_exe': row['exec_path'],
                'force': options['force'],
            }
            if 'port' in options:
                args['port'] = options['port']
            result = self._remote(args)
            yield 1, f'Signal sent to Client PID {result["pid"]}: {result["signal"]} (exit not guaranteed)'
        except (ValueError, RuntimeError, BuiltinInteractionError) as exc:
            yield 0, f'{usage}\n{exc}'
