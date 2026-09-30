import os
import re
import subprocess
import sys

from client.jobs.core.job import Job
from client.runtime.sdk import events


JOB_METADATA = {
    'name': 'wifi_change_event',
    'display_name': 'Wi-Fi Change Event',
    'description': 'Emit a Device Event when the connected Wi-Fi network changes or disconnects.',
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
    ],
}


def _run_text(command: list[str], timeout: float = 5.0) -> str:
    kwargs = {
        'capture_output': True,
        'text': True,
        'errors': 'replace',
        'timeout': timeout,
        'check': False,
    }
    if sys.platform.startswith('win'):
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    result = subprocess.run(command, **kwargs)
    return str(result.stdout or '')


def _windows_wifi_snapshot() -> dict:
    output = _run_text(['netsh', 'wlan', 'show', 'interfaces'])
    values = {}
    for raw_line in output.splitlines():
        if ':' not in raw_line:
            continue
        key, value = raw_line.split(':', 1)
        normalized = key.strip().casefold()
        if normalized == 'ssid':
            values['ssid'] = value.strip()
        elif normalized == 'bssid':
            values['bssid'] = value.strip().lower()
        elif normalized in {'name', '名称'}:
            values.setdefault('interface', value.strip())
    ssid = values.get('ssid', '')
    return {
        'connected': bool(ssid),
        'ssid': ssid,
        'bssid': values.get('bssid', ''),
        'interface': values.get('interface', ''),
    }


def _mac_wifi_device() -> str:
    try:
        output = _run_text(['/usr/sbin/networksetup', '-listallhardwareports'])
    except Exception:
        return 'en0'
    port = ''
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.lower().startswith('hardware port:'):
            port = line.split(':', 1)[1].strip().casefold()
            continue
        if line.lower().startswith('device:') and ('wi-fi' in port or 'wifi' in port or 'airport' in port):
            return line.split(':', 1)[1].strip() or 'en0'
    return 'en0'


def _mac_wifi_snapshot() -> dict:
    airport = '/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport'
    if os.path.exists(airport):
        try:
            output = _run_text([airport, '-I'])
            values = {}
            for raw_line in output.splitlines():
                if ':' not in raw_line:
                    continue
                key, value = raw_line.split(':', 1)
                normalized = key.strip().casefold()
                if normalized == 'ssid':
                    values['ssid'] = value.strip()
                elif normalized == 'bssid':
                    values['bssid'] = value.strip().lower()
            if values.get('ssid'):
                return {
                    'connected': True,
                    'ssid': values.get('ssid', ''),
                    'bssid': values.get('bssid', ''),
                    'interface': _mac_wifi_device(),
                }
        except Exception:
            pass

    device = _mac_wifi_device()
    output = _run_text(['/usr/sbin/networksetup', '-getairportnetwork', device])
    ssid = ''
    if ':' in output:
        candidate = output.strip().split(':', 1)[1].strip()
        lowered = candidate.casefold()
        if candidate and 'not associated' not in lowered and 'not connected' not in lowered:
            ssid = candidate
    return {
        'connected': bool(ssid),
        'ssid': ssid,
        'bssid': '',
        'interface': device,
    }


def _wifi_snapshot() -> dict:
    if sys.platform.startswith('win'):
        return _windows_wifi_snapshot()
    if sys.platform == 'darwin':
        return _mac_wifi_snapshot()
    raise RuntimeError(f'Unsupported platform: {sys.platform}')


def _signature(item: dict) -> tuple:
    return (
        bool(item.get('connected')),
        str(item.get('ssid') or ''),
        str(item.get('bssid') or ''),
        str(item.get('interface') or ''),
    )


class WifiChangeEvent(Job):
    def run(self):
        self.mark_running()
        failed = False
        interval = float(self.get_job_param('interval', 2.0) or 2.0)

        try:
            previous = _wifi_snapshot()
            self.send_to_server(1, f'Wi-Fi watcher started: {previous}', 0)

            while not self.stop_event.wait(interval):
                try:
                    current = _wifi_snapshot()
                except Exception as exc:
                    self.send_to_server(0, f'Wi-Fi snapshot failed: {exc}', 0)
                    continue
                if _signature(current) == _signature(previous):
                    continue

                old_name = str(previous.get('ssid') or 'disconnected')
                new_name = str(current.get('ssid') or 'disconnected')
                message = f'Wi-Fi changed: {old_name} -> {new_name}'
                try:
                    events.emit(
                        'network.wifi.changed',
                        data={'previous': previous, 'current': current},
                        message=message,
                    )
                    self.send_to_server(1, f'Device event emitted: {message}', 0)
                except Exception as exc:
                    self.send_to_server(0, f'Device event emit failed: {exc}', 0)
                previous = current
        except Exception as exc:
            failed = True
            self.is_running = False
            self.stop_event.set()
            self._report_state('error', status=0, text=str(exc))
            self.send_to_server(0, f'Wi-Fi watcher failed: {exc}', 1)
        finally:
            if not failed:
                self.mark_stopped()
