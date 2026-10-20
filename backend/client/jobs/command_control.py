"""Client-side Job runtime control over a dedicated internal message type.

The public ``job`` command and catalog live on the Server. No Client command
method is exported for Job operations; this service only invokes JobManager.
"""
import json
import os

from core.utils.formatting import format_dict
from client.runtime.temp_workspace import make_client_temp_dir, cleanup_temp_path


class ClientJobControl:
    @staticmethod
    def _name(value):
        name = str(value or '').strip().replace('\\', '/')
        return name[:-3].strip('/') if name.endswith('.py') else name.strip('/')

    @classmethod
    def execute(cls, commands, text):
        try:
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError('Job control payload must be an object')
            action = str(payload.get('action') or '').strip()
            manager = commands.socket.runtime.job_manager

            if action == 'start':
                name = cls._name(payload.get('job_name'))
                params = payload.get('params') or {}
                if not name or not isinstance(params, dict):
                    raise ValueError('A Job name and object parameters are required')
                mode = str(payload.get('execution_mode') or 'inproc').strip()
                commands._send_interim_result(1, f'Fetching job: {name}')
                content = commands.client_api.download_job(name, timeout=30)
                temp_dir = make_client_temp_dir('remote_job_temp', prefix='job_')
                try:
                    temp_path = os.path.join(temp_dir, 'remote_job.py')
                    with open(temp_path, 'w', encoding='utf-8') as stream:
                        stream.write(content)
                    commands._send_interim_result(1, f'Client Temp Path: {temp_path}')
                    runtime = manager.start_job(
                        temp_path, name, commands.command_id,
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
                return 1, (
                    f'Background job started: {getattr(runtime, "display_name", name)}\n'
                    f'Mode: {getattr(runtime, "execution_mode", mode)}\n'
                    f'Worker: {getattr(runtime, "worker_name", "unknown")}\n'
                    f'Use "job stop {getattr(runtime, "job_key", name)}" to request stop'
                )
            if action == 'stop':
                key = cls._name(payload.get('job_key'))
                if not key:
                    raise ValueError('Job key is required')
                runtime = manager.stop_job(key)
                return 1, f'Stop request sent: {runtime.display_name}'
            if action == 'ps':
                jobs = manager.list_running_jobs()
                return 1, '\n'.join(jobs) if jobs else 'No background jobs are currently running'
            if action == 'status':
                key = cls._name(payload.get('job_key'))
                if not key:
                    raise ValueError('Job key is required')
                return 1, format_dict(manager.get_job_status(key))
            if action == 'stop_all':
                stopped = manager.stop_all_jobs()
                return 1, ('Stop request sent for:\n' + '\n'.join(stopped)) if stopped else 'No background jobs are currently running'
            raise ValueError(f'Unsupported job control action: {action}')
        except Exception as exc:
            return 0, f'Job control failed: {exc}'
