"""Client-side Job Control: operations return semantic data, never rendered CLI text."""
import os

from core.protocol.control import JobAction
from core.protocol.job_control import build_job_control_result, validate_job_control_request
from core.utils.command_output import ResultDisplay
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
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
                mode = payload['execution_mode']
                scope._send_interim_result(1, f'Downloading Job from Server: {name}')
                content = scope.client_api.download_job(name, timeout=30)
                temp_dir = make_client_temp_dir('remote_job_temp', prefix='job_')
                try:
                    temp_path = os.path.join(temp_dir, 'remote_job.py')
                    with open(temp_path, 'w', encoding='utf-8') as stream:
                        stream.write(content)
                    scope._send_interim_result(1, f'Job saved locally: {temp_path}')
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
                data = {'job_name': name, 'job_key': runtime.job_key, 'job_id': runtime.job_id,
                        'execution_mode': runtime.execution_mode, 'worker_name': runtime.worker_name}
                return 1, build_job_control_result(action, f'Job {name} started ({runtime.execution_mode}).',
                                                   data=data, job_ids=[runtime.job_id])
            if action == JobAction.STOP:
                key = cls._name(payload.get('job_key'))
                runtime = manager.stop_job(key)
                data = {'job_name': runtime.job_key, 'job_id': runtime.job_id,
                        'execution_mode': runtime.execution_mode, 'worker_name': runtime.worker_name,
                        'stop_requested': True}
                return 1, build_job_control_result(action, f'Stop requested for Job {runtime.job_key}.',
                                                   data=data, job_ids=[runtime.job_id])
            if action == JobAction.PS:
                jobs = manager.list_running_jobs()
                return 1, build_job_control_result(action,
                    f'{len(jobs)} running Job(s).' if jobs else 'No background jobs are currently running.',
                    data=jobs, display=ResultDisplay.DATA if jobs else ResultDisplay.MESSAGE)
            if action == JobAction.STATUS:
                key = cls._name(payload.get('job_key'))
                data = manager.get_job_status(key)
                return 1, build_job_control_result(action, f'Job status retrieved: {key}.',
                                                   data=data, display=ResultDisplay.DATA)
            if action == JobAction.STOP_ALL:
                report = manager.stop_all_jobs()
                stopped = [{'job_name': item.get('job_key') or item.get('display_name', '').split('#')[0],
                            'job_id': item['job_id']} for item in report['stopped']]
                errors = list(report['errors'])
                data = {'total': report['total'], 'succeeded': len(stopped), 'failed': len(errors),
                        'stopped': stopped, 'errors': errors}
                if errors:
                    message = f'Stop requested for {len(stopped)} Job(s); {len(errors)} failed.'
                else:
                    message = (f'Stop requested for {len(stopped)} Job(s).' if stopped
                               else 'No background jobs are currently running.')
                return (0 if errors else 1), build_job_control_result(
                    action, message, data=data, status='error' if errors else 'success',
                    job_ids=[item['job_id'] for item in stopped])
            raise ValueError(f'Unsupported Job control action: {action}')
        except (CommandCancelledError, CommandTimeoutError):
            raise
        except Exception as exc:
            return 0, build_job_control_result(action, f'Job {getattr(action, "value", action)} failed: {exc}',
                                               data={'error': str(exc)}, status='error')
