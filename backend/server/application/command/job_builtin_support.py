"""Server-owned Job CLI; only internal job_control packets reach the Client."""
import json
import shlex

from server.application.command.command_types import COMMAND_TYPE_JOB_CONTROL


class JobBuiltinSupport:
    HELP = (
        'job [list|start <name> [--mode inproc|subprocess] [--params JSON]|'
        'stop <name>|ps|status <name>|stop-all]'
    )

    def __init__(self, server, conn, remote_execution_service):
        self.server = server
        self.conn = conn
        self.remote_execution_service = remote_execution_service

    @property
    def client_id(self):
        return str(getattr(getattr(self.conn, 'session_info', None), 'client_id', '') or '').strip()

    def _send(self, action, **payload):
        # Already inside the terminal's foreground command slot: never nest
        # run_foreground_text_command() and attempt to acquire the same slot.
        command = self.server.web_service.job_api.background_job_service._build_job_control_command(action, **payload)
        yield from self.remote_execution_service.stream_command(
            self.conn, command, command_type=COMMAND_TYPE_JOB_CONTROL,
        )

    def job(self, arg=''):
        try:
            parts = shlex.split(str(arg or ''))
        except ValueError as exc:
            yield 0, f'Invalid job arguments: {exc}'
            return
        subcommand = parts[0].lower() if parts else 'list'
        args = parts[1:]
        job_api = self.server.web_service.job_api

        if subcommand in ('list', 'ls'):
            if args:
                yield 0, self.HELP
                return
            jobs = job_api.list_background_job_catalog(self.client_id)
            names = [str(item.get('job_name') or '') for item in jobs if item.get('job_name')]
            yield 1, '\n'.join(names) if names else 'No background jobs available'
            return

        if subcommand == 'start':
            if not args:
                yield 0, self.HELP
                return
            name = args[0]
            mode = None
            params = {}
            remaining = args[1:]
            while remaining:
                flag = remaining.pop(0)
                if flag not in ('--mode', '--params') or not remaining:
                    yield 0, self.HELP
                    return
                value = remaining.pop(0)
                if flag == '--mode':
                    if mode is not None:
                        yield 0, 'Duplicate --mode'
                        return
                    mode = value
                else:
                    try:
                        params = json.loads(value)
                    except ValueError as exc:
                        yield 0, f'Invalid --params JSON: {exc}'
                        return
                    if not isinstance(params, dict):
                        yield 0, '--params must contain a JSON object'
                        return
            try:
                mode = job_api.prepare_background_job_start(self.client_id, name, mode)
            except (ValueError, FileNotFoundError) as exc:
                yield 0, str(exc)
                return
            yield from self._send('start', job_name=name, params=params, execution_mode=mode)
            return

        if subcommand in ('ps', 'stop-all'):
            if args:
                yield 0, self.HELP
                return
            yield from self._send('ps' if subcommand == 'ps' else 'stop_all')
            return

        if subcommand in ('stop', 'status'):
            if len(args) != 1:
                yield 0, self.HELP
                return
            yield from self._send(subcommand, job_key=args[0])
            return

        yield 0, self.HELP
