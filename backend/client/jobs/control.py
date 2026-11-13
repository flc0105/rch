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
                data = {'job_id': runtime.job_id}
                return 1, build_job_control_result(action, f'Stop requested for Job {runtime.job_key}.',
                                                   data=data, job_ids=[runtime.job_id])
            if action == JobAction.PS:
                jobs = manager.list_running_jobs()
                return 1, build_job_control_result(action,
                    '' if jobs else 'No background jobs are currently running.',
                    data=jobs, display=ResultDisplay.DATA)
            if action == JobAction.STATUS:
                key = cls._name(payload.get('job_key'))
                data = manager.get_job_status(key)
                return 1, build_job_control_result(action, '',
                                                   data=data, display=ResultDisplay.DATA)
            if action == JobAction.STOP_ALL:
                report = manager.stop_all_jobs()
                stopped = [{'job_name': item['job_key'], 'job_id': item['job_id']}
                           for item in report['stopped']]
                errors = [{'job_name': item['job_key'], 'job_id': item['job_id'],
                           'message': item['message']} for item in report['errors']]
                if stopped:
                    message = 'Stop requested for: ' + ', '.join(item['job_name'] for item in stopped) + '.'
                else:
                    message = 'No background jobs are currently running.' if not errors else ''
                if errors:
                    failures = '; '.join(f"{item['job_name']} ({item['message']})" for item in errors)
                    message = (message + ' ' if message else '') + f"Failed to stop {'Job' if len(errors) == 1 else 'Jobs'} {failures}."
                # A no-op is a meaningful message, not an invented batch report.
                data = {}
                if stopped:
                    data['stopped'] = stopped
                if errors:
                    data['errors'] = errors
                return (0 if errors else 1), build_job_control_result(
                    action, message, data=data or None, status='error' if errors else 'success',
                    job_ids=[item['job_id'] for item in stopped + errors])
            raise ValueError(f'Unsupported Job control action: {action}')
        except (CommandCancelledError, CommandTimeoutError):
            raise
        except Exception as exc:
            # The originating operation supplies the reason; do not stack a second error prefix.
            return 0, build_job_control_result(action, str(exc).strip() or 'Job operation failed.',
                                               status='error')
