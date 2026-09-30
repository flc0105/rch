import base64
import json
import os
import threading
from datetime import datetime

from core.utils.job_metadata import normalize_job_execution_mode


class BackgroundJobService:
    """
    后台任务应用服务。

    职责：
    - 列出可启动任务
    - 启动 / 停止后台任务
    - 接收客户端通过 HTTP 上报的任务消息/状态/文件
    - 对外提供任务监控数据

    规则：
    - 这里触发的前台远程命令统一走 foreground task 槽
    """

    LIFECYCLE_STATES = {'running', 'stopped', 'error'}

    def __init__(self, event_bus, job_store, remote_execution_service, job_catalog_service, server=None):
        self.event_bus = event_bus
        self.job_store = job_store
        self.remote_execution_service = remote_execution_service
        self.job_catalog_service = job_catalog_service
        self.server = server
        self._lifecycle_event_keys = set()
        self._lifecycle_lock = threading.RLock()

    def _encode_payload_arg(self, payload: dict) -> str:
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        encoded = base64.urlsafe_b64encode(raw).decode('utf-8')
        return f'__json__:{encoded}'

    def _build_start_job_command(self, job_name: str, params=None, execution_mode: str = 'inproc') -> str:
        normalized_job_name = str(job_name or '').strip()
        normalized_params = dict(params or {}) if isinstance(params, dict) else {}
        normalized_mode = normalize_job_execution_mode(execution_mode, default='inproc')

        if not normalized_params and normalized_mode == 'inproc':
            return f'start_job {normalized_job_name}'

        payload = {
            'job_name': normalized_job_name,
            'params': normalized_params,
            'execution_mode': normalized_mode,
        }
        return f'start_job {self._encode_payload_arg(payload)}'

    def _serialize_available_job(self, job_item: dict) -> dict:
        job_name = str(job_item.get('job_name') or job_item.get('name') or job_item.get('job_key') or '').strip()
        display_name = str(job_item.get('display_name') or job_name).strip() or job_name
        job_key = str(job_item.get('job_key') or job_name).strip() or job_name
        description = str(job_item.get('description') or '').strip()
        metadata = job_item.get('metadata') or {}

        return {
            'job_name': job_name,
            'job_key': job_key,
            'display_name': display_name,
            'description': description,
            'metadata': metadata,
            'source': 'job',
        }

    def list_available_jobs(self, client_id: str) -> list[dict]:
        del client_id
        return [
            self._serialize_available_job(item)
            for item in self.job_catalog_service.list_jobs()
            if isinstance(item, dict)
        ]

    def start_job(self, client_id: str, job_name: str, params=None, execution_mode: str = 'inproc') -> dict:
        job_name = (job_name or '').strip()
        if not job_name:
            raise ValueError('job_name is required')

        normalized_params = dict(params or {}) if isinstance(params, dict) else {}
        normalized_mode = normalize_job_execution_mode(execution_mode, default='inproc')

        text = self.remote_execution_service.run_foreground_text_command(
            client_id,
            self._build_start_job_command(job_name, normalized_params, normalized_mode),
            task_type='job_control',
            source='web_background_job',
        )
        return {
            'client_id': client_id,
            'job_name': job_name,
            'params': normalized_params,
            'execution_mode': normalized_mode,
            'message': text,
        }

    def stop_job(self, client_id: str, job_key: str) -> dict:
        job_key = (job_key or '').strip()
        if not job_key:
            raise ValueError('job_key is required')

        text = self.remote_execution_service.run_foreground_text_command(
            client_id,
            f'stop_job {job_key}',
            task_type='job_control',
            source='web_background_job',
        )
        return {
            'client_id': client_id,
            'job_key': job_key,
            'message': text,
        }

    def _calc_duration_seconds(self, started_at: str, stopped_at: str, state: str) -> int:
        if not started_at:
            return 0

        try:
            start_dt = datetime.fromisoformat(started_at)
            end_text = stopped_at
            if not end_text and state not in ('stopped', 'error', 'interrupted'):
                end_text = datetime.now().isoformat()
            end_dt = datetime.fromisoformat(end_text) if end_text else datetime.now()
            return max(int((end_dt - start_dt).total_seconds()), 0)
        except Exception:
            return 0

    def _resolve_client_context(self, client_id: str) -> tuple[str, str]:
        client_id_text = str(client_id or '').strip()
        if not client_id_text:
            return '', ''

        if self.server is not None:
            try:
                session = self.server.get_target_connection_by_client_id(client_id_text)
                info = getattr(session, 'session_info', None)
                machine_id = str(getattr(info, 'machine_id', '') or '').strip()
                hostname = str(getattr(info, 'hostname', '') or '').strip()
                if machine_id:
                    return machine_id, hostname
            except Exception:
                pass

        # For historical/offline views, resolve the durable machine identity
        # from SQLite instead of treating client_id as a permanent owner.
        try:
            conn = self.job_store.database.connection()
            row = conn.execute(
                'SELECT machine_id, snapshot_json FROM recent_devices WHERE client_id = ? LIMIT 1',
                (client_id_text,),
            ).fetchone()
            if row is not None and str(row['machine_id'] or '').strip():
                hostname = ''
                try:
                    snapshot = json.loads(str(row['snapshot_json'] or '{}'))
                    hostname = str(snapshot.get('hostname') or '').strip() if isinstance(snapshot, dict) else ''
                except Exception:
                    hostname = ''
                return str(row['machine_id'] or '').strip(), hostname

            row = conn.execute(
                '''
                SELECT machine_id, snapshot_json
                FROM connection_sessions
                WHERE client_id = ?
                ORDER BY connected_at_ms DESC
                LIMIT 1
                ''',
                (client_id_text,),
            ).fetchone()
            if row is not None and str(row['machine_id'] or '').strip():
                hostname = ''
                try:
                    snapshot = json.loads(str(row['snapshot_json'] or '{}'))
                    hostname = str(snapshot.get('hostname') or '').strip() if isinstance(snapshot, dict) else ''
                except Exception:
                    hostname = ''
                return str(row['machine_id'] or '').strip(), hostname
        except Exception:
            pass

        try:
            previous = self.job_store.list_raw_jobs(client_id=client_id_text)
            if previous:
                return (
                    str(previous[0].get('machine_id') or '').strip(),
                    str(previous[0].get('hostname') or '').strip(),
                )
        except Exception:
            pass

        return '', ''

    def _enrich_report_payload(self, payload: dict) -> dict:
        enriched = dict(payload or {})
        client_id = str(enriched.get('client_id') or '').strip()
        machine_id, hostname = self._resolve_client_context(client_id)
        if machine_id and not str(enriched.get('machine_id') or '').strip():
            enriched['machine_id'] = machine_id
        if hostname and not str(enriched.get('hostname') or '').strip():
            enriched['hostname'] = hostname
        return enriched

    def _serialize_job(self, job: dict, *, include_details: bool = False) -> dict:
        state = job.get('state', '')
        started_at = job.get('started_at', '')
        stopped_at = job.get('stopped_at', '')

        result = {
            'job_id': job.get('job_id', ''),
            'machine_id': job.get('machine_id', ''),
            'client_id': job.get('client_id', ''),
            'hostname': job.get('hostname', ''),
            'job_name': job.get('job_name', ''),
            'job_key': job.get('job_key', ''),
            'display_name': job.get('display_name', ''),
            'thread_name': job.get('thread_name', ''),
            'command_id': job.get('command_id'),
            'execution_mode': job.get('execution_mode', 'inproc'),
            'state': state,
            'created_at': job.get('created_at', ''),
            'started_at': started_at,
            'stopped_at': stopped_at,
            'updated_at': job.get('updated_at', ''),
            'duration_seconds': self._calc_duration_seconds(started_at, stopped_at, state),
            'last_message': job.get('last_message', ''),
            'message_count': job.get('message_count', 0),
            'file_count': job.get('file_count', 0),
        }
        if include_details:
            result['params'] = dict(job.get('params') or {})
            result['messages'] = list(job.get('messages') or [])
            result['files'] = list(job.get('files') or [])
        return result

    def list_jobs(self, client_id: str) -> list[dict]:
        machine_id, _hostname = self._resolve_client_context(client_id)
        jobs = self.job_store.get_jobs_for_scope(machine_id=machine_id, client_id=client_id)
        return [self._serialize_job(job) for job in jobs]

    def get_job(self, client_id: str, job_id: str) -> dict:
        job_id_text = str(job_id or '').strip()
        if not job_id_text:
            raise ValueError('job_id is required')

        machine_id, _hostname = self._resolve_client_context(client_id)
        job = self.job_store.get_job_for_scope(job_id_text, machine_id=machine_id, client_id=client_id)
        if job is None:
            raise FileNotFoundError(f'Background job not found: {job_id_text}')
        return self._serialize_job(job, include_details=True)

    def delete_job_record(self, client_id: str, job_id: str) -> dict:
        job = self.get_job(client_id, job_id)
        state = str(job.get('state') or '').strip().lower()
        if state in ('running', 'stopping'):
            raise ValueError('Stop the background job before deleting its record')

        machine_id, _hostname = self._resolve_client_context(client_id)
        deleted = self.job_store.delete_job(job_id, machine_id=machine_id, client_id=client_id)
        if deleted is None:
            raise FileNotFoundError(f'Background job not found: {job_id}')
        return {
            'job_id': deleted.get('job_id', ''),
            'machine_id': deleted.get('machine_id', ''),
            'client_id': deleted.get('client_id', ''),
            'message': 'Background job record deleted',
        }

    def ingest_report(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError('Invalid background job payload')

        event_type = (payload.get('event_type') or '').strip()
        if not event_type:
            raise ValueError('event_type is required')

        payload = self._enrich_report_payload(payload)

        if event_type == 'status':
            job = self.job_store.apply_status_report(payload)
            serialized = self._serialize_job(job)
            self.event_bus.publish('background_job_status', serialized)
            self._publish_background_job_lifecycle_if_needed(serialized)
            return serialized

        if event_type == 'message':
            job = self.job_store.append_message_report(payload)
            serialized = self._serialize_job(job)
            self.event_bus.publish('background_job_message', serialized)
            return serialized

        if event_type == 'file':
            job = self.job_store.append_file_report(payload)
            serialized = self._serialize_job(job)
            self.event_bus.publish('background_job_file', serialized)
            return serialized

        raise ValueError(f'Unsupported event_type: {event_type}')

    def _publish_background_job_lifecycle_if_needed(self, serialized_job: dict):
        state = str(serialized_job.get('state') or '').strip().lower()
        if state not in self.LIFECYCLE_STATES:
            return

        client_id = str(serialized_job.get('client_id') or '').strip()
        job_id = str(serialized_job.get('job_id') or '').strip()
        if not client_id or not job_id:
            return

        event_key = (client_id, job_id, state)
        with self._lifecycle_lock:
            if event_key in self._lifecycle_event_keys:
                return
            self._lifecycle_event_keys.add(event_key)

        self.event_bus.publish('background_job_lifecycle', {
            'client_id': client_id,
            'job_id': job_id,
            'job_name': serialized_job.get('job_name', ''),
            'job_key': serialized_job.get('job_key', ''),
            'display_name': serialized_job.get('display_name', ''),
            'state': state,
            'status': state,
            'started_at': serialized_job.get('started_at', ''),
            'stopped_at': serialized_job.get('stopped_at', ''),
            'duration_seconds': serialized_job.get('duration_seconds', 0),
            'time': datetime.now().isoformat(),
        })

    def _normalize_job_key(self, value: str) -> str:
        text = str(value or '').strip().replace('\\', '/')
        if text.endswith('.py'):
            text = text[:-3]
        return os.path.basename(text)

    def has_active_job(self, client_id: str, job_name: str) -> bool:
        target_key = self._normalize_job_key(job_name)
        if not target_key:
            return False

        for item in self.list_jobs(client_id):
            job_key = self._normalize_job_key(item.get('job_key') or item.get('job_name') or '')
            state = str(item.get('state') or '').strip().lower()
            if job_key == target_key and state in ('running', 'stopping'):
                return True
        return False
