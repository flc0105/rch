import os
import time

import psutil

from client.jobs.core.job import Job
from client.runtime.sdk import events


JOB_METADATA = {
    'name': 'process_start_event',
    'display_name': 'Process Start Event',
    'description': 'Emit a Device Event when a process whose name/path contains the target text starts.',
    'platforms': ['win', 'mac'],
    'params': [
        {
            'name': 'target_process',
            'type': 'string',
            'default': 'WPS',
            'description': 'Case-insensitive substring to match in process name or executable path.',
        },
        {
            'name': 'interval',
            'type': 'number',
            'default': 1.0,
            'min': 0.25,
            'max': 30,
            'description': 'Polling interval in seconds.',
        },
        {
            'name': 'dedupe_seconds',
            'type': 'number',
            'default': 5.0,
            'min': 0,
            'max': 60,
            'description': 'Group helper processes spawned during one application launch.',
        },
    ],
}


def _process_snapshot(target: str) -> dict[int, dict]:
    needle = str(target or '').strip().casefold()
    result = {}
    if not needle:
        return result

    for proc in psutil.process_iter(['pid', 'name', 'exe', 'create_time']):
        try:
            info = proc.info or {}
            name = str(info.get('name') or '').strip()
            exe = str(info.get('exe') or '').strip()
            haystacks = (name.casefold(), os.path.basename(exe).casefold(), exe.casefold())
            if not any(needle in value for value in haystacks if value):
                continue
            pid = int(info.get('pid') or proc.pid)
            result[pid] = {
                'pid': pid,
                'name': name,
                'exe': exe,
                'create_time': float(info.get('create_time') or 0),
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue
    return result


class ProcessStartEvent(Job):
    def run(self):
        self.mark_running()
        failed = False
        target = str(self.get_job_param('target_process', 'WPS') or 'WPS').strip() or 'WPS'
        interval = float(self.get_job_param('interval', 1.0) or 1.0)
        dedupe_seconds = float(self.get_job_param('dedupe_seconds', 5.0) or 0.0)

        try:
            previous = _process_snapshot(target)
            last_emit_at = 0.0
            self.send_to_server(1, f'Process watcher started: target={target!r} baseline={len(previous)}', 0)

            while not self.stop_event.wait(interval):
                current = _process_snapshot(target)
                new_items = [current[pid] for pid in sorted(set(current) - set(previous))]
                if new_items:
                    now = time.monotonic()
                    if now - last_emit_at >= dedupe_seconds:
                        primary = new_items[0]
                        display = primary.get('name') or os.path.basename(primary.get('exe') or '') or target
                        message = f'Process started: {display}'
                        try:
                            events.emit(
                                'app.process.started',
                                data={'target': target, 'process': primary, 'processes': new_items},
                                message=message,
                            )
                            last_emit_at = now
                            self.send_to_server(
                                1,
                                f'Device event emitted: {message} pid={primary.get("pid")} grouped={len(new_items)}',
                                0,
                            )
                        except Exception as exc:
                            self.send_to_server(0, f'Device event emit failed: {exc}', 0)
                    else:
                        self.send_to_server(1, f'Process launch helper(s) suppressed: count={len(new_items)}', 0)
                previous = current
        except Exception as exc:
            failed = True
            self.is_running = False
            self.stop_event.set()
            self._report_state('error', status=0, text=str(exc))
            self.send_to_server(0, f'Process watcher failed: {exc}', 1)
        finally:
            if not failed:
                self.mark_stopped()
