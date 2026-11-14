"""Server-owned Job CLI; only internal job_control packets reach the Client."""
from core.protocol.control import ControlDomain, JobAction
import time

from server.application.command.command_types import COMMAND_TYPE_CONTROL
from core.platform.catalog_visibility import visible_on_platform
from core.protocol.job_control import build_job_control_request, validate_job_control_result
from core.utils.command_output import ResultDataShape, render_result_payload
from core.protocol.result_envelope import ResultEnvelope


class JobBuiltinSupport:
    HELP = 'job list|ps|start|stop|status|stop-all|logs [--name NAME] [--json]'

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

    @staticmethod
    def _failure(message, output_format):
        return render_result_payload(ResultEnvelope(status='error', message=str(message)).as_payload(), output_format)

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
            yield 0, self._failure('Job control returned no result', output_format)
            return
        status, text, *rest = pending_result
        try:
            result = validate_job_control_result(text, action)
        except (ValueError, TypeError):
            if status == 1:
                yield (0, self._failure('Invalid Job control response', output_format), *rest)
            else:
                yield pending_result  # Preserve structured cancellation/timeout and EOF.
            return
        from core.protocol.message_queue import ResultChunk
        view = 'data' if action in (JobAction.PS, JobAction.STATUS) and status == 1 else 'message'
        shape = ResultDataShape.TABLE if action == JobAction.PS else ResultDataShape.FLAT
        yield ResultChunk(status, render_result_payload(result, output_format, view=view, shape=shape),
                          getattr(pending_result, 'eof', True), terminal_authoritative=True,
                          event=getattr(pending_result, 'event', None))

    def _job_logs(self, name, follow=False):
        """Stream reports for a single fully parsed Job key."""
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

    def execute_subcommand(self, invocation):
        """Consume one typed Server invocation; no CLI string parsing here."""
        from core.protocol.result_envelope import ResultEnvelope
        subcommand = invocation.action
        args = invocation.arguments
        output_format = invocation.output_format

        if subcommand == 'list':
            platform = str(getattr(getattr(self.conn, 'session_info', None), 'os_alias', '') or '')
            jobs = [item for item in self.job_catalog_service.list_background_job_catalog()
                    if visible_on_platform(item, platform)]
            rows = [{'name': str(item.get('job_name') or ''),
                     'display_name': str(item.get('display_name') or ''),
                     'description': str(item.get('description') or '')}
                    for item in jobs if item.get('job_name')]
            result = ResultEnvelope(message='No background jobs available' if not rows else '',
                                    data=rows).as_payload()
            yield 1, render_result_payload(result, output_format, view='data', shape=ResultDataShape.TABLE)
            return

        if subcommand == 'logs':
            yield from self._job_logs(args['name'], args['follow'])
            return

        if subcommand == 'start':
            params = args['params']
            try:
                mode = self.background_job_service.prepare_job_start(self.client_id, args['name'], args['mode'])
            except (ValueError, FileNotFoundError) as exc:
                yield 0, self._failure(str(exc), output_format)
                return
            yield from self._send(JobAction.START, output_format=output_format,
                                  job_name=args['name'], params=params, execution_mode=mode)
            return

        if subcommand == 'ps':
            yield from self._send(JobAction.PS, output_format=output_format)
            return
        if subcommand == 'stop-all':
            yield from self._send(JobAction.STOP_ALL, output_format=output_format)
            return
        if subcommand in ('stop', 'status'):
            yield from self._send(JobAction(subcommand), output_format=output_format, job_key=args['name'])
            return
        raise ValueError(f'Unsupported Job subcommand: {subcommand}')
