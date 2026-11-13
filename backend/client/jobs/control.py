"""Client-side Job runtime control over a dedicated internal message type.

The public ``job`` command and catalog live on the Server. No Client command
method is exported for Job operations; this service only invokes JobManager.
"""
import os
from core.protocol.control import JobAction
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError

from core.utils.formatting import format_dict
from core.protocol.job_control import build_job_control_result, validate_job_control_request
from client.runtime.temp_workspace import make_client_temp_dir, cleanup_temp_path


class JobControl:
    @staticmethod
    def _name(value):
        name = str(value or '').strip().replace('\\', '/')
        return name[:-3].strip('/') if name.endswith('.py') else name.strip('/')

    @classmethod
    def execute(cls, manager, scope, action, payload):
        try:
            validate_job_control_request(action, payload)

            if action == JobAction.START:
                name = cls._name(payload.get('job_name'))
                params = payload.get('params') or {}
                if not name or not isinstance(params, dict):
                    raise ValueError('A Job name and object parameters are required')
                mode = str(payload.get('execution_mode') or 'inproc').strip()
                scope._send_interim_result(1, f'Fetching job: {name}')
                content = scope.client_api.download_job(name, timeout=30)
                temp_dir = make_client_temp_dir('remote_job_temp', prefix='job_')
                try:
                    temp_path = os.path.join(temp_dir, 'remote_job.py')
                    with open(temp_path, 'w', encoding='utf-8') as stream:
                        stream.write(content)
                    scope._send_interim_result(1, f'Client Temp Path: {temp_path}')
                    runtime = manager.start_job(
                        temp_path, name, scope.command_id,
                        job_params=params, cleanup_path=temp_dir, execution_mode=mode,
                    )
                    for obj in (runtime, getattr(runtime, 'job_instance', None)):
                        if obj is not None:
                            obj._temp_script_path = temp_path
                            obj._remote_job_source = 'job_api'
                            obj._remote_script_name = name
                except Exception:
                    cleanup_temp_path(temp_dir)
                    raise
                message = (
                    f'Background job started: {getattr(runtime, "display_name", name)}\n'
                    f'Mode: {getattr(runtime, "execution_mode", mode)}\n'
                    f'Worker: {getattr(runtime, "worker_name", "unknown")}\n'
                    f'Use "job stop {getattr(runtime, "job_key", name)}" to request stop'
                )
                return 1, build_job_control_result(JobAction.START, message, job_id=runtime.job_id)
            if action == JobAction.STOP:
                key = cls._name(payload.get('job_key'))
                if not key:
                    raise ValueError('Job key is required')
                runtime = manager.stop_job(key)
                return 1, build_job_control_result(JobAction.STOP, f'Stop request sent: {runtime.display_name}', job_id=runtime.job_id)
            if action == JobAction.PS:
                jobs = manager.list_running_jobs()
                return 1, build_job_control_result(JobAction.PS, '\n'.join(jobs) if jobs else 'No background jobs are currently running', jobs=jobs)
            if action == JobAction.STATUS:
                key = cls._name(payload.get('job_key'))
                if not key:
                    raise ValueError('Job key is required')
                return 1, build_job_control_result(JobAction.STATUS, format_dict(manager.get_job_status(key)))
            if action == JobAction.STOP_ALL:
                report = manager.stop_all_jobs()
                names = [item['display_name'] for item in report['stopped']]
                errors = report['errors']
                message = ('Stop request sent for:\n' + '\n'.join(names)) if names else 'No background jobs are currently running'
                if errors:
                    message += '\nErrors:\n' + '\n'.join(errors)
                return (1 if not errors else 0), build_job_control_result(
                    JobAction.STOP_ALL, message, job_ids=[item['job_id'] for item in report['stopped']],
                    total=report['total'], succeeded=len(names), errors=errors,
                )
            raise ValueError(f'Unsupported job control action: {action}')
        except (CommandCancelledError, CommandTimeoutError):
            raise
        except Exception as exc:
            return 0, (build_job_control_result(action, f'Job control failed: {exc}', succeeded=0, errors=[str(exc)])
                       if action in (JobAction.START, JobAction.STOP, JobAction.STOP_ALL) else
                       build_job_control_result(action, f'Job control failed: {exc}')
                       if action in (JobAction.PS, JobAction.STATUS) else str(exc))
