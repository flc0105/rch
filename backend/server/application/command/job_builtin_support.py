"""Server-owned Job CLI; only internal job_control packets reach the Client."""
import json
from core.protocol.control import ControlDomain, JobAction
import shlex
import time

from server.application.command.command_types import COMMAND_TYPE_CONTROL
from core.platform.catalog_visibility import visible_on_platform
from core.protocol.job_control import build_job_control_request, validate_job_control_result
from core.utils.command_output import parse_output_format, strip_output_format_arg, render_result_payload


class JobBuiltinSupport:
    HELP = (
        'job [list|start <name> [--mode inproc|subprocess] [--params JSON]|'
        'stop <name>|ps|status <name>|stop-all|logs <name> [--follow|-f]]'
    )

    def __init__(self, server, conn, remote_execution_service, background_job_service, job_catalog_service, history_entry_id_provider=None):
        self.server = server
        self.conn = conn
        self.remote_execution_service = remote_execution_service
        self.background_job_service = background_job_service
        self.job_catalog_service = job_catalog_service
        self.history_entry_id_provider = history_entry_id_provider or (lambda: '')

    @property
    def client_id(self):
        return str(getattr(getattr(self.conn, 'session_info', None), 'client_id', '') or '').strip()

    def _send(self, action, *, output_format="text", **payload):
        # Already inside the terminal's foreground slot: never acquire it again.
        request = build_job_control_request(action, **payload)
        entry_id = self.history_entry_id_provider() or ''
        kwargs = {'command_type': COMMAND_TYPE_CONTROL, 'domain': ControlDomain.JOB, 'action': action}
        if entry_id:
            kwargs['history_entry_id'] = entry_id
        pending_result = None
        for item in self.remote_execution_service.stream_command(self.conn, '', payload=request, **kwargs):
            # JSON mode produces a single machine-readable document on stdout;
            # progress is still recorded by the shared request Activity observer.
            if pending_result is not None and output_format != 'json':
                yield pending_result
            pending_result = item
        if pending_result is None:
            yield 0, 'Job control returned no result'
            return
        status, text, *rest = pending_result
        try:
            result = validate_job_control_result(text, action)
        except (ValueError, TypeError):
            if status == 1:
                yield (0, 'Invalid Job control response', *rest)
            else:
                yield pending_result  # Preserve structured cancellation/timeout and EOF.
            return
        from core.protocol.message_queue import ResultChunk
        yield ResultChunk(status, render_result_payload(result, output_format), getattr(pending_result, 'eof', True), terminal_authoritative=True)

    def _job_logs(self, args):
        """Stream persisted reports through the shared Job application service."""
        follow = False
        names = []
        for token in args:
            if token in ('--follow', '-f'):
                if follow:
                    yield 0, 'Specify --follow only once'
                    return
                follow = True
            elif token.startswith('-'):
                yield 0, f'Unknown job logs option: {token}'
                return
            else:
                names.append(token)
        if len(names) != 1:
            yield 0, 'Usage: job logs <name> [--follow|-f]'
            return

        name = names[0]
        try:
            # The list is newest first. Keep following this exact job_id rather
            # than switching silently when a new instance with the same name runs.
            rows = self.background_job_service.list_jobs(self.client_id)
            row = next((item for item in rows if isinstance(item, dict)
                        and any(str(item.get(key) or '').casefold() == name.casefold()
                                for key in ('job_key', 'job_name', 'job_id'))), None)
            if not row:
                yield 0, f'No reported Job found for: {name}'
                return
            job_id = str(row.get('job_id') or '')
            if not job_id:
                yield 0, 'Job record is missing its job_id'
                return
            job = self.background_job_service.get_job(self.client_id, job_id)
            yield 1, (f"Job {job.get('job_key') or job.get('job_name') or name} "
                      f"[{job.get('state') or 'unknown'}] {job_id}")
            cursor = 0
            while True:
                # These records describe historical Job output. An error report
                # is not an error in the 'job logs' query itself.
                for message in job.get('messages') or []:
                    if not isinstance(message, dict):
                        continue
                    try:
                        seq = int(message.get('seq') or 0)
                    except (ValueError, TypeError):
                        continue
                    if seq <= cursor:
                        continue
                    cursor = seq
                    text = str(message.get('text') or '')
                    if text:
                        if int(message.get('status') or 0) == 0:
                            text = '[error] ' + text
                        yield 1, text
                if not follow:
                    return
                if str(job.get('state') or '').lower() not in ('running', 'stopping'):
                    yield 1, '[Job finished]'
                    return
                # Foreground Task cancellation is the existing Web/CLI Ctrl+C
                # mechanism. No separate control command or CLI parser is needed.
                for _ in range(10):
                    task = self.conn.get_foreground_task() or {}
                    if task.get('cancel_requested'):
                        yield 0, 'command cancelled'
                        return
                    time.sleep(0.2)
                job = self.background_job_service.get_job(self.client_id, job_id)
        except (ValueError, FileNotFoundError, LookupError) as exc:
            yield 0, str(exc)

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
        if subcommand == 'list':
            if args not in ([], ['--json']):
                yield 0, self.HELP
                return
            platform = str(getattr(getattr(self.conn, 'session_info', None), 'os_alias', '') or '')
            jobs = [item for item in self.job_catalog_service.list_background_job_catalog()
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

        if subcommand == 'logs':
            yield from self._job_logs(args)
            return

        output_format = parse_output_format(remaining)
        remaining = strip_output_format_arg(remaining)
        args = shlex.split(remaining)

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
                mode = self.background_job_service.prepare_job_start(self.client_id, name, mode)
            except (ValueError, FileNotFoundError) as exc:
                yield 0, str(exc)
                return
            yield from self._send(JobAction.START, output_format=output_format, job_name=name, params=params, execution_mode=mode)
            return

        if subcommand in ('ps', 'stop-all'):
            if args:
                yield 0, self.HELP
                return
            yield from self._send(JobAction.PS if subcommand == 'ps' else JobAction.STOP_ALL, output_format=output_format)
            return

        if subcommand in ('stop', 'status'):
            if len(args) != 1:
                yield 0, self.HELP
                return
            yield from self._send(JobAction(subcommand), output_format=output_format, job_key=args[0])
            return

        yield 0, self.HELP
