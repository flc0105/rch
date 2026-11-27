"""Server-owned Job CLI; only internal job_control packets reach the Client."""
from core.protocol.control import ControlDomain, JobAction
import time

from server.application.command.command_types import COMMAND_TYPE_CONTROL
from core.platform.catalog_visibility import visible_on_platform
from core.protocol.job_control import build_job_control_request, validate_job_control_result
from core.utils.command_output import ResultDataShape, render_result_payload, resolve_presentation
from core.protocol.result_envelope import ResultEnvelope, ResultEvent, ResultStreamState


class JobBuiltinSupport:
    HELP = 'job list [--format|-f LAYOUT] [--json] | ps|start|stop|status|stop-all|logs'

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
        result = ResultEvent.completed('error', str(message))
        return result.with_text(render_result_payload(result.event, output_format))

    def _send(self, action, *, output_format="text", layout=None, **payload):
        # Already inside the terminal's foreground slot: never acquire it again.
        request = build_job_control_request(action, **payload)
        entry_id = self.history_entry_id_provider() or ''
        kwargs = {'command_type': COMMAND_TYPE_CONTROL, 'domain': ControlDomain.JOB, 'action': action}
        if entry_id:
            kwargs['history_entry_id'] = entry_id
        state = ResultStreamState()
        for item in self.remote_execution_service.stream_command(self.conn, '', payload=request, **kwargs):
            state.accept(item)
            # JSON mode has one machine-readable document; progress remains in Activity.
            if item.terminal_status is None and output_format != 'json':
                yield item
        completed = state.completion
        if completed is None:
            result = ResultEvent.completed('interrupted', 'Job control returned no result')
            yield result.with_text(render_result_payload(result.event, output_format))
            return
        try:
            result = validate_job_control_result(completed.event, action)
        except (ValueError, TypeError):
            yield self._failure('Invalid Job control response', output_format) if completed.succeeded else completed
            return
        view = 'data' if action in (JobAction.PS, JobAction.STATUS) and completed.succeeded else 'message'
        shape = ResultDataShape.TABLE if action == JobAction.PS else ResultDataShape.FLAT
        yield completed.with_text(render_result_payload(result, output_format, view=view, shape=layout or shape))

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
                yield ResultEvent.completed('error', f'No reported Job found for: {name}')
                return
            job_id = str(row.get('job_id') or '')
            if not job_id:
                yield ResultEvent.completed('error', 'Job record is missing its job_id')
                return
            job = self.background_job_service.get_job(self.client_id, job_id)
            yield ResultEvent.chunk(f"Job {job.get('job_key') or job.get('job_name') or name} "
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
                        yield ResultEvent.chunk(text)
                if not follow:
                    yield ResultEvent.completed()
                    return
                if str(job.get('state') or '').lower() not in ('running', 'stopping'):
                    yield ResultEvent.completed(message='[Job finished]')
                    return
                # Foreground Task cancellation is the existing Web/CLI Ctrl+C
                # mechanism. No separate control command or CLI parser is needed.
                for _ in range(10):
                    task = self.conn.get_foreground_task() or {}
                    if task.get('cancel_requested'):
                        yield ResultEvent.completed('cancelled', 'command cancelled')
                        return
                    time.sleep(0.2)
                job = self.background_job_service.get_job(self.client_id, job_id)
        except (ValueError, FileNotFoundError, LookupError) as exc:
            yield ResultEvent.completed('error', str(exc))

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
            output_format, layout = resolve_presentation(args, ResultDataShape.LINES)
            text = render_result_payload(result, output_format, view='data',
                                         shape=layout, line_field='name')
            yield ResultEvent(result, text)
            return

        if subcommand == 'logs':
            yield from self._job_logs(args['name'], args['follow'])
            return

        if subcommand == 'start':
            params = args['params']
            try:
                mode = self.background_job_service.prepare_job_start(self.client_id, args['name'], args['mode'])
            except (ValueError, FileNotFoundError) as exc:
                yield self._failure(str(exc), output_format)
                return
            yield from self._send(JobAction.START, output_format=output_format,
                                  job_name=args['name'], params=params, execution_mode=mode)
            return

        if subcommand == 'ps':
            fmt, layout = resolve_presentation(args, ResultDataShape.TABLE)
            yield from self._send(JobAction.PS, output_format=fmt, layout=layout)
            return
        if subcommand == 'stop-all':
            yield from self._send(JobAction.STOP_ALL, output_format=output_format)
            return
        if subcommand in ('stop', 'status'):
            fmt, layout = (resolve_presentation(args, ResultDataShape.FLAT)
                           if subcommand == 'status' else (output_format, None))
            yield from self._send(JobAction(subcommand), output_format=fmt, layout=layout, job_key=args['name'])
            return
        raise ValueError(f'Unsupported Job subcommand: {subcommand}')
