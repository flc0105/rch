"""Flat Linux host and Client process information for getinfo."""

import getpass
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from core.utils.command_output import StructuredCommandResult


class LinuxSystemService:
    def __init__(self, owner):
        self.owner = owner

    @staticmethod
    def _read(path):
        try:
            return Path(path).read_text(encoding='utf-8', errors='replace').strip()
        except (OSError, ValueError):
            return ''

    @staticmethod
    def _run(args):
        try:
            result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    text=True, timeout=3, check=False)
            return result.stdout.strip() if result.returncode == 0 else ''
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return ''

    def _os_release(self):
        data = {}
        for line in self._read('/etc/os-release').splitlines():
            if '=' in line:
                key, value = line.split('=', 1)
                data[key.strip()] = value.strip().strip('"')
        return data

    @staticmethod
    def _valid_dmi(value):
        return value and value.lower() not in {
            'none', 'null', 'o.e.m.', 'to be filled by o.e.m.', 'to be filled by oem',
            'default string', 'system product name', 'system version',
            'not specified', 'not applicable',
        }

    def _host(self):
        for keys in (('sys_vendor', 'product_name', 'product_version'),
                     ('board_vendor', 'board_name')):
            parts = []
            for key in keys:
                value = self._read(f'/sys/class/dmi/id/{key}')
                if self._valid_dmi(value) and value.lower() not in [p.lower() for p in parts]:
                    parts.append(value)
            if parts:
                return ' '.join(parts)
        return socket.gethostname()

    def _cpu_model(self):
        for line in self._read('/proc/cpuinfo').splitlines():
            if line.startswith('model name') and ':' in line:
                return line.split(':', 1)[1].strip()
        return None

    def _memory(self):
        fields = {}
        for line in self._read('/proc/meminfo').splitlines():
            if ':' in line:
                key, value = line.split(':', 1)
                try:
                    fields[key.strip()] = int(value.strip().split()[0])
                except (IndexError, ValueError):
                    continue
        total = fields.get('MemTotal')
        available = fields.get('MemAvailable')
        total_gb = round(total / (1024 ** 2), 2) if total is not None else None
        available_gb = round(available / (1024 ** 2), 2) if available is not None else None
        used_gb = round((total - available) / (1024 ** 2), 2) if total is not None and available is not None else None
        return total_gb, used_gb, available_gb

    def _gpu(self):
        if shutil.which('nvidia-smi'):
            output = self._run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'])
            if output:
                return ', '.join(dict.fromkeys(x.strip() for x in output.splitlines() if x.strip()))
        if shutil.which('lspci'):
            output = self._run(['lspci'])
            entries = []
            for line in output.splitlines():
                if any(kind in line.lower() for kind in ('vga compatible controller', '3d controller', 'display controller')):
                    entries.append(line.split(': ', 1)[-1].strip())
            return ', '.join(dict.fromkeys(entries)) or None
        return None

    @staticmethod
    def _route_ip():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(('8.8.8.8', 80))
                return sock.getsockname()[0]
        except OSError:
            return None

    def _desktop_resolution(self):
        if not os.environ.get('DISPLAY'):
            return None
        if shutil.which('xrandr'):
            for line in self._run(['xrandr', '--current']).splitlines():
                if ' connected' in line:
                    for token in line.split():
                        if 'x' in token and '+' in token:
                            return token
        if shutil.which('xdpyinfo'):
            for line in self._run(['xdpyinfo']).splitlines():
                if line.strip().startswith('dimensions:'):
                    return line.split(':', 1)[-1].strip().split()[0]
        return None

    def collect_system_info(self):
        try:
            release = self._os_release()
            total, used, available = self._memory()
            pid = os.getpid()
            cmdline = self._read(f'/proc/{pid}/cmdline').replace('\x00', ' ').strip() or None
            data = {
                'distro': release.get('NAME'),
                'os_version': release.get('VERSION') or release.get('VERSION_ID'),
                'pretty_name': release.get('PRETTY_NAME'),
                'kernel': platform.release(),
                'arch': platform.machine(),
                'hostname': socket.gethostname(),
                'host': self._host(),
                'cpu_model': self._cpu_model(),
                'cpu_cores': os.cpu_count(),
                'memory_total_gb': total,
                'memory_used_gb': used,
                'memory_available_gb': available,
                'gpu': self._gpu(),
                'ip': self._route_ip(),
                'python_version': platform.python_version(),
                'python_executable': sys.executable,
                'package_manager': next((name for name in (
                    'apt', 'dnf', 'yum', 'pacman', 'zypper', 'apk', 'emerge', 'xbps-install'
                ) if shutil.which(name)), None),
                'default_shell': os.environ.get('SHELL'),
                'current_shell': self._read(f'/proc/{os.getppid()}/comm') or None,
                'has_desktop': bool(any(os.environ.get(key) for key in (
                    'DISPLAY', 'WAYLAND_DISPLAY', 'XDG_CURRENT_DESKTOP', 'DESKTOP_SESSION'
                ))),
                'resolution': self._desktop_resolution(),
                'user': getpass.getuser(),
                'is_root': os.geteuid() == 0,
                'cwd': os.getcwd(),
                'pid': pid,
                'ppid': os.getppid(),
                'process_name': self._read(f'/proc/{pid}/comm') or None,
                'cmdline': cmdline,
                'exe': os.path.realpath(f'/proc/{pid}/exe') if os.path.exists(f'/proc/{pid}/exe') else None,
            }
            return StructuredCommandResult(status=1, data=data, shape='dict', width=24)
        except Exception as exc:
            return 0, f'Failed to get Linux system info: {exc}'
