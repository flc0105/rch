import psutil

from client.jobs.core.job import Job
from client.monitor.manager import DeviceMonitorManager
from client.runtime.sdk import events


JOB_METADATA = {
    'name': 'external_storage_event',
    'display_name': 'External Storage Event',
    'description': 'Emit a Device Event when a new user-visible external/removable volume is mounted.',
    'platforms': ['win', 'mac'],
    'params': [
        {
            'name': 'interval',
            'type': 'number',
            'default': 2.0,
            'min': 0.5,
            'max': 30,
            'description': 'Polling interval in seconds.',
        },
        {
            'name': 'include_network',
            'type': 'boolean',
            'default': False,
            'description': 'Also emit when a network volume appears.',
        },
    ],
}


def _volume_key(item: dict) -> str:
    return str(item.get('mountpoint') or item.get('device') or '').strip().casefold()


class ExternalStorageEvent(Job):
    def _snapshot(self, include_network: bool) -> dict[str, dict]:
        # Reuse the same storage normalization used by Device Monitor so Windows
        # drive type/labels and macOS /Volumes handling stay consistent.
        monitor = DeviceMonitorManager(None)
        payload = monitor._collect_storage(psutil)
        result = {}
        for item in payload.get('volumes') or []:
            if item.get('system'):
                continue
            if not include_network and item.get('kind') == 'network':
                continue
            key = _volume_key(item)
            if key:
                result[key] = dict(item)
        return result

    def run(self):
        self.mark_running()
        failed = False
        interval = float(self.get_job_param('interval', 2.0) or 2.0)
        include_network = bool(self.get_job_param('include_network', False))

        try:
            previous = self._snapshot(include_network)
            self.send_to_server(1, f'External storage watcher started; baseline={len(previous)}', 0)

            while not self.stop_event.wait(interval):
                current = self._snapshot(include_network)
                added_keys = [key for key in current if key not in previous]
                for key in added_keys:
                    item = current[key]
                    name = str(item.get('name') or item.get('mountpoint') or item.get('device') or 'volume')
                    message = f'External storage attached: {name}'
                    try:
                        events.emit('storage.volume.attached', data=item, message=message)
                        self.send_to_server(1, f'Device event emitted: {message} mount={item.get("mountpoint")!r}', 0)
                    except Exception as exc:
                        self.send_to_server(0, f'Device event emit failed: {exc}', 0)
                previous = current
        except Exception as exc:
            failed = True
            self.is_running = False
            self.stop_event.set()
            self._report_state('error', status=0, text=str(exc))
            self.send_to_server(0, f'External storage watcher failed: {exc}', 1)
        finally:
            if not failed:
                self.mark_stopped()
