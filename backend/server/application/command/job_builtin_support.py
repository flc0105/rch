"""Server-owned Job CLI; only internal job_control packets reach the Client."""
import json
import shlex

from server.application.command.command_types import COMMAND_TYPE_JOB_CONTROL
from core.platform.catalog_visibility import visible_on_platform
from core.utils.job_control_result import decode_job_control_result


class JobBuiltinSupport:
    HELP = (
        'job [list|start <name> [--mode inproc|subprocess] [--params JSON]|'
        'stop <name>|ps|status <name>|stop-all]'
    )

    def __init__(self, server, conn, remote_execution_service, history_entry_id_provider=None):
        self.server = server
        self.conn = conn
        self.remote_execution_service = remote_execution_service
        self.history_entry_id_provider = history_entry_id_provider or (lambda: '')

    @property
    def client_id(self):
        return str(getattr(getattr(self.conn, 'session_info', None), 'client_id', '') or '').strip()

    def _send(self, action, **payload):
        # Already inside the terminal's foreground slot: never acquire it again.
        command = self.server.web_service.job_api.background_job_service._build_job_control_command(action, **payload)
        actions = {'start': 'start_job', 'stop': 'stop_job', 'stop_all': 'stop_all_jobs'}
        history = getattr(self.server, 'command_history_orchestrator', None)
        entry_id = self.history_entry_id_provider() or ''
        if history is not None and action in actions:
            arguments = {key: payload[key] for key in ('job_name', 'job_key', 'execution_mode') if key in payload}
            entry_id = history.begin_background_job_execution(
                self.conn, actions[action], arguments, origin='cli', entry_id=entry_id,
            )
        kwargs = {'command_type': COMMAND_TYPE_JOB_CONTROL}
        if entry_id and action in actions:
            kwargs['history_entry_id'] = entry_id
        pending_result = None
        for item in self.remote_execution_service.stream_command(self.conn, command, **kwargs):
            # Progress packets are readable text. Only the last packet is the
            # management result, so never display its raw internal JSON.
            if pending_result is not None:
                yield pending_result
            pending_result = item
        if pending_result is None:
            if action in actions:
                yield 0, 'Job control returned no result'
            return
        if action not in actions:
            yield pending_result
            return
        status, text, *rest = pending_result
        try:
            result = decode_job_control_result(text, action)
        except (ValueError, TypeError):
            if status == 1:
                yield (0, 'Invalid Job control response', *rest)
            else:
                yield pending_result  # Transport / Client failure, not structured.
            return
        if history is not None:
            history.record_background_job_result(self.conn, entry_id, result)
        yield (status, result['message'], *rest)

    def job(self, arg=''):
        from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
        try:
            _, subcommand, remaining = SERVER_COMMAND_REGISTRY.parse('job', arg)
        except ValueError as exc:
            yield 0, str(exc)
            return
        yield from self.execute_subcommand(subcommand, remaining)

    def execute_subcommand(self, subcommand, remaining=''):
        try:
            args = shlex.split(str(remaining or ''))
        except ValueError as exc:
            yield 0, f'Invalid job arguments: {exc}'
            return
        job_api = self.server.web_service.job_api

        if subcommand == 'list':
            if args not in ([], ['--json']):
                yield 0, self.HELP
                return
            platform = str(getattr(getattr(self.conn, 'session_info', None), 'os_alias', '') or '')
            jobs = [item for item in job_api.list_background_job_catalog(self.client_id)
                    if visible_on_platform(item, platform)]
            if args == ['--json']:
                yield 1, json.dumps([{'name': str(item.get('job_name') or ''),
                                      'display_name': str(item.get('display_name') or ''),
                                      'description': str(item.get('description') or '')}
                                     for item in jobs if item.get('job_name')], ensure_ascii=False, indent=2)
                return
            names = [str(item.get('job_name') or '') for item in jobs if item.get('job_name')]
            yield 1, '\n'.join(names) if names else 'No background jobs available'
            return

        if subcommand == 'start':
            from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
            try:
                positional, flags = SERVER_COMMAND_REGISTRY.parse_arguments('job', 'start', remaining)
            except ValueError as exc:
                yield 0, str(exc)
                return
            if len(positional) != 1:
                yield 0, self.HELP
                return
            name = positional[0]
            mode = flags.get('mode')
            params = {}
            if 'params' in flags:
                try:
                    params = json.loads(flags['params'])
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
