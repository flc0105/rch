"""Server-only cleanup planning, retention policy and execution."""
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from core.utils.logger import logger
from core.utils.formatting import format_bytes_precise
from server.application.maintenance.cleanup_plan import Candidate
from server.runtime.server_logging import server_rotation_lock, loader_log_lock, SERVER_LOG_BACKUP_COUNT, SERVER_LOG_FILENAME


@dataclass(frozen=True)
class ScanIssue:
    message: str


def _file_candidate(*args, **kwargs):
    try:
        return Candidate.file(*args, **kwargs)
    except (ValueError, OSError) as exc:
        return ScanIssue(str(exc))


@dataclass(frozen=True)
class CleanupProvider:
    label: str
    scan: Callable[[], Iterable[Candidate | ScanIssue]]
    delete: Callable[[Candidate, dict], None]
    startup_residue: bool = False
    minimum_age_days: int = 0
    manual_only: bool = False


class ServerCleanupService:
    """One scan/plan/execute path for manual and startup maintenance."""

    LOG_PREFIX = 'server_cleanup_'
    PLAN_TTL = 600
    MAX_PLANS = 4

    def __init__(self, *, event_bus, notification_history_service, artifact_service,
                 agent_output_registry, cleanup_items, start_delay_seconds: int,
                 log_root_dir: str, settings_store, database, runtime_dir):
        self.event_bus = event_bus
        self.notification_history_service = notification_history_service
        self.artifact_service = artifact_service
        self.agent_output_registry = agent_output_registry
        self.settings_store = settings_store
        self.database = database
        self.cleanup_items = tuple(cleanup_items or ())
        self.start_delay_seconds = max(0, int(start_delay_seconds or 0))
        self.log_root_dir = os.path.abspath(log_root_dir)
        self.runtime_dir = Path(runtime_dir).absolute()
        self._lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._stopping = False
        self._startup_scheduled = False
        self._plans = {}
        self._runs = {}
        os.makedirs(self.log_root_dir, exist_ok=True)
        self._providers = {
            'agent_build_temp': CleanupProvider('Agent Build Temp',
                lambda: self._paths('agent_build_temp', self.runtime_dir / 'agent_build_tmp', r'agent_build_[A-Za-z0-9_]+', directories=True), self._delete_path, True),
            'agent_transient_outputs': CleanupProvider('Transient Agent Outputs', self._agent_outputs, self._delete_agent, True),
            'preview_cache': CleanupProvider('Preview Cache', self._previews, self._delete_preview, True),
            'upload_tmp': CleanupProvider('Upload Temporary Files', self._upload_residue, self._delete_upload, True),
            'cleanup_logs': CleanupProvider('Cleanup Logs',
                lambda: self._paths('cleanup_logs', self.log_root_dir, r'server_cleanup_[A-Za-z0-9_-]+\.log'), self._delete_path),
            'notifications': CleanupProvider('Notifications', self._notifications, self._delete_notification),
            'server_rotated_logs': CleanupProvider('Server Rotated Logs', self._rotated_logs, self._delete_rotated_log, minimum_age_days=1),
            'go_loader_logs': CleanupProvider('Go Loader Logs', self._loader_logs, self._delete_loader_log, minimum_age_days=1),
            'tcp_transfer_residue': CleanupProvider('TCP Transfer Residue', self._tcp_residue, self._delete_path, True),
            'bootstrap_temp': CleanupProvider('Bootstrap Temporary Files',
                lambda: self._paths('bootstrap_temp', self.runtime_dir / 'bootstrap_tmp', r'bootstrap_[A-Za-z0-9_]+\.(py|ps1)'), self._delete_path, True),
            'orphan_artifacts': CleanupProvider('Orphan Artifact Files', self._orphan_artifacts, self._delete_orphan, True, manual_only=True),
        }
        # Capture only prior-instance candidates before starting request workers.
        # Current-process staging, builds, previews and artifact allocations are
        # deliberately not collected while their owners may still reference them.
        self._startup_candidates = {}
        self._startup_errors = {}
        for key, provider in self._providers.items():
            if provider.startup_residue:
                try:
                    self._startup_candidates[key] = list(provider.scan())
                except Exception as exc:
                    self._startup_errors[key] = str(exc)

    def schedule_startup_cleanup(self):
        with self._lock:
            if self._startup_scheduled:
                return False
            self._startup_scheduled = True
            timer = threading.Timer(self.start_delay_seconds, self._run_startup_cleanup)
            timer.name = 'server-startup-cleanup'
            timer.daemon = True
            timer.start()
            return True

    def _run_startup_cleanup(self):
        try:
            self.run_cleanup()
        except Exception:
            logger.error('Server startup cleanup failed', exc_info=True)
        finally:
            self.database.close_thread_connection()

    def _defaults(self):
        return {'enabled': True, 'categories': {
            key: {'enabled': key in self.cleanup_items,
                  'days': 30 if key in ('notifications', 'go_loader_logs') else 7 if key in ('cleanup_logs', 'server_rotated_logs') else 0}
            for key, provider in self._providers.items() if not provider.manual_only}}

    def get_settings(self):
        defaults = self._defaults()
        saved = self.settings_store.read()
        if not saved:
            return defaults
        # A newly introduced category gets its explicit default, not a saved path.
        categories = saved.get('categories', {})
        for key in defaults['categories']:
            if key in categories:
                defaults['categories'][key] = categories[key]
        defaults['enabled'] = saved.get('enabled', True)
        return self._validate_settings(defaults)

    def _validate_settings(self, payload):
        if not isinstance(payload, dict) or type(payload.get('enabled')) is not bool:
            raise ValueError('Invalid automatic cleanup settings')
        categories = payload.get('categories')
        if not isinstance(categories, dict) or set(categories) != set(self._defaults()['categories']):
            raise ValueError('Invalid cleanup categories')
        normalized = {}
        for key, rule in categories.items():
            if not isinstance(rule, dict) or type(rule.get('enabled')) is not bool or type(rule.get('days')) is not int:
                raise ValueError('Invalid cleanup retention rule')
            days = rule['days']
            minimum = max(self._providers[key].minimum_age_days, 1 if key == 'notifications' else 0)
            if not minimum <= days <= 3650:
                raise ValueError(f'Invalid retention days for {key}')
            normalized[key] = {'enabled': rule['enabled'], 'days': days}
        return {'enabled': payload['enabled'], 'categories': normalized}

    def save_settings(self, payload):
        value = self._validate_settings(payload)
        self.settings_store.write(value)
        return value

    @staticmethod
    def _paths(category, root, pattern, directories=False):
        root = Path(root).absolute()
        if not root.exists():
            return
        if root.resolve() != root:
            raise ValueError('Unsafe cleanup root')
        for path in sorted(root.iterdir()):
            if not re.fullmatch(pattern, path.name) or path.is_symlink():
                continue
            if (path.is_dir() if directories else path.is_file()):
                yield _file_candidate(category, path, path)

    def _agent_outputs(self):
        for record in self.agent_output_registry.startup_transient_outputs():
            name = record['file_name']
            path = Path(self.agent_output_registry.output_dir) / name
            if path.is_file():
                yield _file_candidate('agent_transient_outputs', name, path, record=True,
                                     signature=record['created_at'])

    def _previews(self):
        for row, path in self.artifact_service.startup_preview_entries():
            yield _file_candidate('preview_cache', row['artifact_id'], path,
                                 row['original_name'], record=True, signature=row['saved_at'])

    def _upload_residue(self):
        for candidate in self._paths('upload_tmp', self.artifact_service.upload_tmp_dir, r'[0-9a-f]{32}', directories=True):
            if isinstance(candidate, ScanIssue) or not self.artifact_service.is_upload_temp_reserved(candidate.key):
                yield candidate

    def _notifications(self):
        # Internal complete snapshot, not the Web notification page size.
        rows = self.notification_history_service.list_cleanup_candidates()
        for row in rows:
            try:
                modified = datetime.fromisoformat(row['shown_at'].replace('Z', '+00:00')).timestamp()
            except (ValueError, TypeError, AttributeError):
                modified = time.time()  # unknown timestamp is not eligible for age-based cleanup
            yield Candidate('notifications', row['id'], row['title'], modified, record=True,
                            signature=json.dumps(row, sort_keys=True), id=uuid.uuid4().hex)

    def _rotated_logs(self):
        with server_rotation_lock(self.runtime_dir):
            yield from self._paths('server_rotated_logs', self.runtime_dir, re.escape(SERVER_LOG_FILENAME) + r'\.(?:' + '|'.join(str(i) for i in range(1, SERVER_LOG_BACKUP_COUNT + 1)) + ')')

    def _loader_logs(self):
        with loader_log_lock:
            for candidate in self._paths('go_loader_logs', self.runtime_dir / 'logs', r'go_loader_\d{8}-\d{2}\.log'):
                if isinstance(candidate, ScanIssue) or candidate.name != datetime.now().strftime('go_loader_%Y%m%d-%H.log'):
                    yield candidate

    def _tcp_residue(self):
        for path in self.artifact_service.maintenance_residue_paths('tcp'):
            yield _file_candidate('tcp_transfer_residue', path, path)

    def _orphan_artifacts(self):
        for path in self.artifact_service.maintenance_residue_paths('orphan'):
            yield _file_candidate('orphan_artifacts', path, path)

    def _eligible(self, candidate):
        if not candidate.unchanged():
            return False
        if candidate.category == 'preview_cache':
            return self.artifact_service.is_cleanup_preview(candidate.key)
        if candidate.category == 'agent_transient_outputs':
            return self.agent_output_registry.is_cleanup_output(candidate.key)
        if candidate.category == 'upload_tmp':
            return not self.artifact_service.is_upload_temp_reserved(candidate.key)
        if candidate.category == 'orphan_artifacts':
            return self.artifact_service.is_orphan_artifact_path(candidate.key)
        return True

    def _scan(self, rules=None, *, details=True):
        groups, candidates = [], {}
        now = time.time()
        for key, provider in self._providers.items():
            rule = (rules or {}).get(key, {})
            if rules is not None and (provider.manual_only or not rule.get('enabled')):
                continue
            error = self._startup_errors.get(key, '')
            found = []
            issues = [error] if error else []
            try:
                source = self._startup_candidates.get(key, ()) if provider.startup_residue else provider.scan()
                age = max(provider.minimum_age_days, rule.get('days', 0))
                for candidate in source:
                    if isinstance(candidate, ScanIssue):
                        issues.append(candidate.message)
                        continue
                    if candidate.modified <= now - age * 86400 and self._eligible(candidate):
                        found.append(candidate)
            except Exception as exc:
                issues.append(str(exc))
            error = "; ".join(issues[:5])
            if len(issues) > 5:
                error += f"; {len(issues)-5} more scan errors"
            candidates.update((item.id, item) for item in found)
            groups.append({'key': key, 'label': provider.label, 'manual_only': provider.manual_only,
                           'startup_residue': provider.startup_residue, 'minimum_age_days': provider.minimum_age_days,
                           'error': error, 'size': sum(c.size for c in found),
                           'records': sum(c.record for c in found), 'count': len(found),
                           'entries': [c.as_dict() for c in found] if details else []})
        return groups, candidates

    def preview(self):
        if not self._operation_lock.acquire(blocking=False):
            raise ValueError('Server maintenance is busy')
        try:
            groups, candidates = self._scan()
            with self._lock:
                now = time.monotonic()
                self._plans = {key: value for key, value in self._plans.items() if value[0] > now}
                while len(self._plans) >= self.MAX_PLANS:
                    self._plans.pop(next(iter(self._plans)))
                plan_id = uuid.uuid4().hex
                self._plans[plan_id] = (now + self.PLAN_TTL, candidates)
            return {'plan_id': plan_id, 'groups': groups, 'settings': self.get_settings(),
                    'bytes': sum(g['size'] for g in groups), 'records': sum(g['records'] for g in groups),
                    'missing_artifacts': self.artifact_service.missing_artifact_count()}
        finally:
            self._operation_lock.release()

    def summary(self):
        if not self._operation_lock.acquire(blocking=False):
            raise ValueError('Server maintenance is busy')
        try:
            groups, _ = self._scan(details=False)
            return {'bytes': sum(g['size'] for g in groups), 'records': sum(g['records'] for g in groups),
                    'count': sum(g['count'] for g in groups), 'incomplete': any(g['error'] for g in groups)}
        finally:
            self._operation_lock.release()

    def is_busy(self):
        return self._operation_lock.locked()

    def reserve_stop(self):
        """Close maintenance admission before a restart or shutdown is accepted."""
        if not self._operation_lock.acquire(blocking=False):
            return False
        try:
            if self._stopping:
                return False
            self._stopping = True
            return True
        finally:
            self._operation_lock.release()

    def _require_running(self):
        if self._stopping:
            raise ValueError('Server maintenance is already pending')

    def execute(self, plan_id, selected_ids):
        if not isinstance(plan_id, str) or not isinstance(selected_ids, list) or not selected_ids or any(not isinstance(i, str) for i in selected_ids):
            raise ValueError('Select cleanup candidates')
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError('Duplicate cleanup selection')
        if not self._operation_lock.acquire(blocking=False):
            raise ValueError('Server maintenance is busy')
        try:
            self._require_running()
            with self._lock:
                plan = self._plans.get(plan_id)
                if not plan or plan[0] <= time.monotonic():
                    raise ValueError('Cleanup plan expired; refresh the scan')
                if not set(selected_ids) <= plan[1].keys():
                    raise ValueError('Unknown cleanup candidate')
                self._plans.pop(plan_id)
                candidates = [plan[1][i] for i in selected_ids]
                run_id = self._build_run_id()
                while len(self._runs) >= 4:
                    self._runs.pop(next(iter(self._runs)))
                self._runs[run_id] = {'run_id': run_id, 'state': 'running', 'total': len(candidates),
                                      'processed': 0, 'cancel_requested': False, 'result': None}
            worker = threading.Thread(target=self._manual_worker, args=(run_id, candidates),
                                      name='server-cleanup', daemon=True)
            accepted = self.get_run(run_id)
            try:
                worker.start()
            except BaseException:
                with self._lock:
                    self._runs.pop(run_id, None)
                raise
            return accepted
        except BaseException:
            self._operation_lock.release()
            raise

    def get_run(self, run_id):
        with self._lock:
            if run_id not in self._runs:
                raise FileNotFoundError('Cleanup run not found')
            return dict(self._runs[run_id])

    def cancel_run(self, run_id):
        with self._lock:
            if run_id not in self._runs:
                raise FileNotFoundError('Cleanup run not found')
            if self._runs[run_id]['state'] == 'running':
                self._runs[run_id]['cancel_requested'] = True
            return dict(self._runs[run_id])

    def _manual_worker(self, run_id, candidates):
        final = {'state': 'failed', 'error': 'Cleanup interrupted'}
        try:
            result = self._execute_candidates(candidates, 'manual', run_id=run_id)
            final = {'state': 'completed', 'result': result}
        except Exception as exc:
            logger.exception('Server cleanup failed')
            final = {'state': 'failed', 'error': str(exc)}
        finally:
            try:
                self.database.close_thread_connection()
            finally:
                with self._lock:
                    self._runs[run_id].update(final)
                    self._operation_lock.release()

    def run_cleanup(self, trigger='startup'):
        with self._operation_lock:
            if self._stopping:
                return None
            settings = self.get_settings()
            if not settings['enabled']:
                return None
            groups, candidates = self._scan(settings['categories'], details=False)
            errors = {g['key']: g['error'] for g in groups if g['error']}
            return self._execute_candidates(list(candidates.values()), trigger, errors)

    def _execute_candidates(self, candidates, trigger, scan_errors=None, *, run_id=None):
        manual = run_id is not None
        run_id, started = run_id or self._build_run_id(), time.time()
        results = {}
        for key, error in (scan_errors or {}).items():
            results[key] = self._new_item_result(key)
            results[key]['errors'].append(error)
        stopped = 0
        for index, item in enumerate(candidates):
            if manual and self.get_run(run_id)['cancel_requested']:
                stopped = len(candidates) - index
                break
            result = results.setdefault(item.category, self._new_item_result(item.category))
            try:
                if not self._eligible(item):
                    result['skipped_count'] = result.get('skipped_count', 0) + 1
                    result['skipped'] = True
                    result['skip_reason'] = 'Candidate changed or is in use'
                    continue
                self._providers[item.category].delete(item, result)
            except Exception as exc:
                result['errors'].append(f'{item.name}: {exc}')
            finally:
                if manual:
                    with self._lock:
                        self._runs[run_id]['processed'] = index + 1
        ended = time.time()
        summary = self._build_summary(run_id=run_id, trigger=trigger, started_at=self._iso_time(started),
            finished_at=self._iso_time(ended), duration_ms=int((ended-started)*1000), item_results=list(results.values()))
        summary['skipped_count'] = sum(r.get('skipped_count', 0) for r in results.values())
        summary['stopped_count'] = stopped
        summary['log_url'] = f'/api/server-cleanup/runs/{run_id}/log' if self._write_log(summary) else ''
        try:
            self._publish_completed(summary)
        except Exception:
            logger.exception('Failed to publish cleanup completion')
        return summary

    @staticmethod
    def _delete_path(item, result):
        item.remove_files(result)

    def _delete_upload(self, item, result):
        self.artifact_service.delete_upload_residue_for_cleanup(item.key, lambda: item.remove_files(result))

    @staticmethod
    def _count_record_file(item, result):
        result['removed_records'] += 1
        result['removed_files'] += 1
        result['bytes_freed'] += item.size
        result['entries'].append({'kind': 'file', 'path': item.entries[0].path, 'size': item.size, 'detail': item.name})

    def _delete_agent(self, item, result):
        self.agent_output_registry.delete_transient_for_cleanup(item.key, item.signature, item.unchanged)
        self._count_record_file(item, result)

    def _delete_preview(self, item, result):
        self.artifact_service.delete_preview_for_cleanup(item.key, item.signature, item.unchanged)
        self._count_record_file(item, result)

    def _delete_orphan(self, item, result):
        self.artifact_service.delete_orphan_for_cleanup(item.key, lambda: item.remove_files(result))

    def _delete_notification(self, item, result):
        removed = self.notification_history_service.cleanup_notifications(
            [item.key], expected={item.key: json.loads(item.signature)}).get('removed', [])
        result['removed_records'] += len(removed)
        if removed:
            result['entries'].append({'kind': 'record', 'path': f'notification:{item.key}', 'size': 0, 'detail': item.name})
        else:
            result['skipped_count'] = result.get('skipped_count', 0) + 1

    def _delete_rotated_log(self, item, result):
        with server_rotation_lock(self.runtime_dir):
            item.remove_files(result)

    def _delete_loader_log(self, item, result):
        with loader_log_lock:
            if item.name == datetime.now().strftime('go_loader_%Y%m%d-%H.log'):
                raise ValueError('Active loader log')
            item.remove_files(result)

    def database_info(self):
        return self.database.space_info()

    def optimize_database(self):
        if not self._operation_lock.acquire(blocking=False):
            raise ValueError('Server maintenance is busy')
        try:
            self._require_running()
            return self.database.optimize_space()
        finally:
            self._operation_lock.release()

    def get_log_path(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
            raise FileNotFoundError('cleanup log not found')
        path = Path(self.log_root_dir) / f'{self.LOG_PREFIX}{run_id}.log'
        if path.resolve() != path or not path.is_file():
            raise FileNotFoundError('cleanup log not found')
        return str(path)
    @staticmethod
    def _new_item_result(name: str) -> dict:
        return {
            'name': name,
            'removed_files': 0,
            'removed_dirs': 0,
            'removed_records': 0,
            'bytes_freed': 0,
            'entries': [],
            'errors': [],
            'skipped': False,
            'skip_reason': '',
        }

    @staticmethod
    def _build_run_id() -> str:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        return f'{stamp}-{uuid.uuid4().hex[:10]}'

    @staticmethod
    def _iso_time(epoch_value: float) -> str:
        return datetime.fromtimestamp(float(epoch_value), tz=timezone.utc).isoformat().replace('+00:00', 'Z')

    def _build_summary(self, *, run_id: str, trigger: str, started_at: str, finished_at: str,
                       duration_ms: int, item_results: list[dict]) -> dict:
        return {
            'run_id': run_id,
            'trigger': str(trigger or '').strip() or 'startup',
            'started_at': started_at,
            'finished_at': finished_at,
            'duration_ms': int(duration_ms or 0),
            'items': item_results,
            'removed_files': sum(int(item.get('removed_files') or 0) for item in item_results),
            'removed_dirs': sum(int(item.get('removed_dirs') or 0) for item in item_results),
            'removed_records': sum(int(item.get('removed_records') or 0) for item in item_results),
            'bytes_freed': sum(int(item.get('bytes_freed') or 0) for item in item_results),
            'error_count': sum(len(item.get('errors') or []) for item in item_results),
        }

    def _write_log(self, summary: dict) -> str:
        run_id = summary['run_id']
        log_path = os.path.join(self.log_root_dir, f'{self.LOG_PREFIX}{run_id}.log')
        lines = [
            f'Server Cleanup Run: {run_id}',
            f'Trigger: {summary.get("trigger", "")}',
            f'Started: {summary.get("started_at", "")}',
            f'Finished: {summary.get("finished_at", "")}',
            f'Duration: {summary.get("duration_ms", 0)} ms',
            '',
            'Summary:',
            f'  Removed files: {summary.get("removed_files", 0)}',
            f'  Removed directories: {summary.get("removed_dirs", 0)}',
            f'  Removed records: {summary.get("removed_records", 0)}',
            f'  Freed size: {format_bytes_precise(summary.get("bytes_freed", 0))} ({summary.get("bytes_freed", 0)} bytes)',
            f'  Errors: {summary.get("error_count", 0)}',
            f'  Skipped: {summary.get("skipped_count", 0)}',
            f'  Not processed: {summary.get("stopped_count", 0)}',
        ]

        for item in summary.get('items') or []:
            lines.extend([
                '',
                f'[{item.get("name", "")}]',
                f'  Removed files: {item.get("removed_files", 0)}',
                f'  Removed directories: {item.get("removed_dirs", 0)}',
                f'  Removed records: {item.get("removed_records", 0)}',
                f'  Freed size: {format_bytes_precise(item.get("bytes_freed", 0))} ({item.get("bytes_freed", 0)} bytes)',
            ])
            if item.get('skipped'):
                lines.append(f'  Skipped: {item.get("skip_reason", "")}')
            for entry in item.get('entries') or []:
                size = int(entry.get('size') or 0)
                detail = str(entry.get('detail') or '').strip()
                suffix = f' · {detail}' if detail else ''
                lines.append(
                    f'  {str(entry.get("kind") or "item").upper()} '
                    f'{format_bytes_precise(size)} · {entry.get("path", "")}{suffix}'
                )
            for error in item.get('errors') or []:
                lines.append(f'  ERROR · {error}')

        try:
            with open(log_path, 'w', encoding='utf-8') as file_obj:
                file_obj.write('\n'.join(lines))
                file_obj.write('\n')
            return log_path
        except Exception:
            logger.error('Failed to write server cleanup log: %s', log_path, exc_info=True)
            return ''

    def _publish_completed(self, summary: dict):
        if self.event_bus is None:
            return
        self.event_bus.publish('server_cleanup_completed', {
            'run_id': summary.get('run_id', ''),
            'trigger': summary.get('trigger', ''),
            'state': 'completed',
            'removed_files': summary.get('removed_files', 0),
            'removed_dirs': summary.get('removed_dirs', 0),
            'removed_records': summary.get('removed_records', 0),
            'bytes_freed': summary.get('bytes_freed', 0),
            'error_count': summary.get('error_count', 0),
            'skipped_count': summary.get('skipped_count', 0),
            'stopped_count': summary.get('stopped_count', 0),
            'log_url': summary.get('log_url', ''),
        })
