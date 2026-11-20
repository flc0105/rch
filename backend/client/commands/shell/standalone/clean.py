"""Preview and clean Client-owned residue."""

from functools import partial

from client.commands.runtime.interrupts import cancel_policy
from client.commands.shell.decorators import shell_command
from client.commands.shell.standalone._cleanup_plan import ClientCleanupService
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.runtime.execution.interaction_service import CommandInteractions
from core.protocol.result_envelope import ResultEnvelope
from core.utils.formatting import get_size


@shell_command('Clean Client residue and obsolete bundle releases', group='maintenance', interaction=True)
@cancel_policy('cooperative')
def clean(self, arg=''):
    """Preview selectable cleanup categories; --no-confirm executes without Broker."""
    options = str(arg or '').strip()
    if options not in ('', '--no-confirm'):
        return 0, 'Usage: clean [--no-confirm]'
    try:
        service = ClientCleanupService(
            checkpoint=self._checkpoint,
            progress_callback=partial(_on_cleanup_progress, self.emit_progress),
        )
        self._set_timeout(240)
        self.emit_progress('Scanning cleanup directories...', level='info')
        plan = service.plan()
        had_scan_errors = any(item['errors'] for item in plan['items'])
        candidates = [
            entry for entry in plan['items'] if entry['paths'] or entry.get('has_empty_dirs')
        ]
        if not candidates:
            if had_scan_errors:
                return _cleanup_scan_failure(plan)
            return 1, ResultEnvelope(status='success', message='Nothing to clean.').as_payload()

        chosen = {entry['name'] for entry in candidates}
        if options == '--no-confirm':
            # An idle but live *other* Client cannot be proven inactive
            # without additional metadata; require manual Preview for logs.
            chosen.discard('client_logs')
        else:
            rows = []
            for entry in candidates:
                scanned_paths = [str(path) for path in (entry.get('scanned_paths') or [])]
                rows.append({
                    'category': entry['name'],
                    'directory': ' | '.join(scanned_paths) if scanned_paths else 'managed cleanup directory',
                    'files': f"{int(entry.get('removed_files') or 0):,}",
                    'directories': f"{int(entry.get('removed_dirs') or 0):,}",
                    'size': get_size(float(entry.get('bytes_freed') or 0)),
                })
            preview = {
                'summary': [
                    {'label': 'Locations', 'value': str(len(rows))},
                    {'label': 'Files', 'value': f"{sum(i['removed_files'] for i in candidates):,}"},
                    {'label': 'Directories', 'value': f"{sum(i['removed_dirs'] for i in candidates):,}"},
                    {'label': 'Size', 'value': get_size(sum(float(i['bytes_freed'] or 0) for i in candidates))},
                ],
                'columns': [
                    {'key': 'category', 'label': 'Cleanup item'},
                    {'key': 'directory', 'label': 'Directory'},
                    {'key': 'files', 'label': 'Files'},
                    {'key': 'directories', 'label': 'Directories'},
                    {'key': 'size', 'label': 'Size'},
                ],
                'rows': rows,
                'row_ids': [entry['name'] for entry in candidates],
                'notice': 'The selected cleanup directories will be permanently cleaned. The current running release is protected.',
            }
            self.emit_progress('Waiting for cleanup approval...', level='info')
            chosen = set(CommandInteractions(self).select_preview_rows(
                'Delete selected Client residue?', preview,
                title='Client Cleanup — Delete Plan'))
            if not chosen:
                return 1, ResultEnvelope(
                    status='success', message='No cleanup categories selected; nothing was deleted.'
                ).as_payload()

        if not chosen:
            if had_scan_errors:
                return _cleanup_scan_failure(plan)
            return 1, ResultEnvelope(
                status='success', message='No safe cleanup targets selected; nothing was deleted.'
            ).as_payload()

        result = service.execute_plan(plan, chosen)
        final_status, final_message = _cleanup_completion(result)
        return (1 if final_status in ('success', 'partial') else 0), ResultEnvelope(
            status=final_status, message=final_message,
        ).as_payload()
    except (CommandCancelledError, CommandTimeoutError):
        raise
    except Exception as exc:
        return 0, f'Failed to clean Client residue: {exc}'


def _cleanup_directory_label(item: dict) -> str:
    directories = [str(path) for path in (item.get('scanned_paths') or []) if str(path)]
    return ' | '.join(directories) if directories else 'managed cleanup directory'


def _on_cleanup_progress(emit, phase: str, item: dict):
    name = str(item.get('name') or 'cleanup').strip()
    files = int(item.get('removed_files') or 0)
    directories = int(item.get('removed_dirs') or 0)
    size = get_size(float(item.get('bytes_freed') or 0))
    errors = item.get('errors') or []

    if phase == 'scan_completed':
        for error in errors:
            emit(f'Failed to scan {name}: {error}', level='warning')
        if files or directories:
            emit(
                f'Scanned {name} — {_cleanup_directory_label(item)}: '
                f'{files:,} files, {directories:,} directories, {size}',
                level='info',
            )
        elif not errors:
            emit(
                f'Scanned {name} — {_cleanup_directory_label(item)}: nothing to clean',
                level='info',
            )
        return

    if phase == 'clean_started':
        emit(
            f'Cleaning {name} — {_cleanup_directory_label(item)}...',
            level='info',
        )
        return

    if phase == 'clean_completed':
        if errors:
            level = 'warning' if files or directories else 'error'
            emit(
                f'{name}: partially cleaned — {files:,} files, {directories:,} directories deleted; '
                f'{size} freed; {len(errors):,} failed',
                level=level,
            )
            for error in errors:
                emit(f'Failed to delete: {error}', level='error')
        elif files or directories:
            emit(
                f'Cleaned {name} — {files:,} files, {directories:,} directories deleted; {size} freed',
                level='success',
            )
        else:
            emit(f'{name}: nothing to delete', level='info')


def _cleanup_completion(result: dict) -> tuple[str, str]:
    files = int(result.get('removed_files') or 0)
    directories = int(result.get('removed_dirs') or 0)
    freed = get_size(float(result.get('bytes_freed') or 0))
    errors = int(result.get('error_count') or 0)
    scan_errors = result['scan_error_count']
    removed_any = files > 0 or directories > 0
    removed = f'{files:,} files and {directories:,} directories deleted; {freed} freed'

    if scan_errors:
        issues = f'{scan_errors:,} scan error(s)'
        if errors:
            issues += f', {errors:,} deletion error(s)'
        if removed_any:
            return 'partial', f'Cleanup partially completed: {removed}; {issues}.'
        return 'error', f'Cleanup incomplete: {issues}; nothing was removed.'
    if errors and removed_any:
        status = 'partial'
        message = f'Cleanup partially completed: {removed}; {errors:,} failed.'
    elif errors:
        status = 'error'
        message = f'Cleanup failed: {errors:,} item(s) could not be deleted; nothing was removed.'
    elif removed_any:
        status = 'success'
        message = f'Cleanup completed: {removed}.'
    else:
        status = 'success'
        message = 'Nothing to clean.'
    return status, message


def _cleanup_scan_failure(plan: dict) -> tuple[int, dict]:
    failed_items = [item for item in (plan.get('items') or []) if item.get('errors')]
    error_count = sum(len(item.get('errors') or []) for item in failed_items)
    names = ', '.join(str(item.get('name') or 'unknown') for item in failed_items)
    locations = f' ({names})' if names else ''
    message = (
        f'Cleanup scan failed{locations}: {error_count} error(s); '
        'nothing was deleted.'
    )
    return 0, ResultEnvelope(status='error', message=message).as_payload()
