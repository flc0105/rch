import os

from client.jobs.core.job import Job
from client.runtime.sdk import events


JOB_METADATA = {
    'name': 'clipboard_file_event',
    'display_name': 'Clipboard File Event',
    'description': 'Emit a Device Event when a new file list appears in the local clipboard.',
    'platforms': ['win', 'mac'],
    'params': [
        {
            'name': 'interval',
            'type': 'number',
            'default': 0.75,
            'min': 0.2,
            'max': 10,
            'description': 'Polling interval in seconds.',
        },
    ],
}


def _file_signature(paths) -> tuple[str, ...]:
    return tuple(os.path.normcase(os.path.abspath(str(path))) for path in paths if path)


class ClipboardFileEvent(Job):
    def run(self):
        self.mark_running()
        failed = False
        interval = float(self.get_job_param('interval', 0.75) or 0.75)
        initialized = False
        last_signature = ()

        try:
            clipboard_manager = getattr(getattr(self.server, 'runtime', None), 'clipboard_manager', None)
            if clipboard_manager is None:
                raise RuntimeError('Clipboard manager is unavailable')

            while not self.stop_event.is_set():
                try:
                    snapshot = clipboard_manager.adapter.get_snapshot()
                except Exception:
                    self.stop_event.wait(interval)
                    continue

                paths = snapshot.get('paths') if isinstance(snapshot, dict) and snapshot.get('kind') == 'files' else []
                signature = _file_signature(paths or [])

                if initialized and signature and signature != last_signature:
                    names = [os.path.basename(path.rstrip(os.sep)) or path for path in signature]
                    try:
                        events.emit(
                            'clipboard.files.changed',
                            data={
                                'count': len(signature),
                                'paths': list(signature),
                                'names': names,
                            },
                            message=f'{len(signature)} file(s) appeared in the clipboard',
                        )
                    except Exception as exc:
                        self.send_to_server(0, f'Device event emit failed: {exc}', 0)

                initialized = True
                last_signature = signature
                self.stop_event.wait(interval)
        except Exception as exc:
            failed = True
            self.is_running = False
            self.stop_event.set()
            self._report_state('error', status=0, text=str(exc))
            self.send_to_server(0, f'Clipboard file watcher failed: {exc}', 1)
        finally:
            if not failed:
                self.mark_stopped()
