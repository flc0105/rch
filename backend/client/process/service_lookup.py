"""Look up the service directly associated with a PID on desktop platforms.

Returns a service/unit/job identifier, or None when no direct match is visible.
Create one PidServiceLookup per process-listing operation to reuse its snapshot.
"""

import re
import subprocess

from core.platform.platform_identity import detect_platform_alias


_UNIT_SUFFIX = (".service", ".socket")
_USER_MANAGER = re.compile(r"^user@\d+\.service$")


def _linux_service(pid):
    try:
        with open(f"/proc/{pid}/cgroup", encoding="utf-8", errors="replace") as stream:
            lines = stream.read().splitlines()
    except OSError:
        return None

    for line in lines:
        path = line.split(":", 2)[-1]
        for part in reversed(path.split("/")):
            if part.endswith(_UNIT_SUFFIX) and not _USER_MANAGER.fullmatch(part):
                return part
    return None


def _windows_service_index():
    try:
        import psutil
    except ImportError:
        return {}

    by_pid = {}
    try:
        for service in psutil.win_service_iter():
            try:
                pid = service.pid()
                name = service.name()
            except (psutil.Error, OSError):
                continue
            if pid and name:
                by_pid.setdefault(int(pid), set()).add(name)
    except (psutil.Error, OSError, AttributeError):
        pass
    return {pid: ", ".join(sorted(names)) for pid, names in by_pid.items()}


def _mac_service_index():
    # launchctl list describes jobs visible in the caller's bootstrap domain.
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}

    by_pid = {}
    for line in result.stdout.splitlines():
        fields = line.split(None, 2)
        if len(fields) != 3 or not fields[0].isdigit():
            continue
        pid, label = int(fields[0]), fields[2]
        # Anonymous launchd bookkeeping entries are not owned launchd jobs.
        if pid > 0 and label and not label.startswith("0x"):
            by_pid.setdefault(pid, set()).add(label)
    return {pid: ", ".join(sorted(names)) for pid, names in by_pid.items()}


class PidServiceLookup:
    """Resolve PID to service name, caching desktop service indexes per instance.

    Linux: nearest non-manager systemd service/socket in /proc/PID/cgroup.
    Windows: Service Control Manager entries whose service PID matches.
    macOS: running launchd jobs in the caller's bootstrap domain.
    """

    def __init__(self, os_alias=None):
        self.os_alias = os_alias or detect_platform_alias()
        self._index = None

    def get(self, pid):
        """Return a name (multiple names comma-separated), or None."""
        try:
            pid = int(pid)
        except (TypeError, ValueError, OverflowError):
            return None
        if pid <= 0:
            return None

        if self.os_alias == "linux":
            return _linux_service(pid)
        if self.os_alias not in ("win", "mac"):
            return None
        if self._index is None:
            self._index = (
                _windows_service_index()
                if self.os_alias == "win"
                else _mac_service_index()
            )
        return self._index.get(pid)


def get_service_name(pid, os_alias=None):
    """Convenience lookup for one PID; use PidServiceLookup for many PIDs."""
    return PidServiceLookup(os_alias).get(pid)
