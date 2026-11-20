"""Mounted volumes used by the desktop Monitor and Client commands."""
import ctypes
import os


def collect_storage_volumes(psutil, os_alias: str) -> list[dict]:
    volumes = []
    seen_mounts = set()

    for partition in psutil.disk_partitions(all=False):
        mountpoint = str(partition.mountpoint or '').strip()
        if not mountpoint or mountpoint in seen_mounts:
            continue
        if not _should_include_volume(os_alias, partition):
            continue

        seen_mounts.add(mountpoint)
        try:
            usage = psutil.disk_usage(mountpoint)
        except Exception:
            continue

        meta = _volume_metadata(os_alias, partition)
        normalized_usage = _normalize_volume_usage(os_alias, partition, usage)
        volumes.append({
            'name': meta['name'],
            'mountpoint': mountpoint,
            'device': str(partition.device or ''),
            'fstype': str(partition.fstype or ''),
            'kind': meta['kind'],
            'system': bool(meta['system']),
            'total': normalized_usage['total'],
            'used': normalized_usage['used'],
            'free': normalized_usage['free'],
            'percent': normalized_usage['percent'],
        })

    volumes.sort(key=lambda item: (not item.get('system'), str(item.get('name') or '').casefold()))
    return volumes

def _normalize_volume_usage(os_alias, partition, usage) -> dict:
    total = int(getattr(usage, 'total', 0) or 0)
    used = int(getattr(usage, 'used', 0) or 0)
    free = int(getattr(usage, 'free', 0) or 0)
    percent = round(float(getattr(usage, 'percent', 0) or 0), 1)

    mountpoint = str(getattr(partition, 'mountpoint', '') or '').strip()
    fstype = str(getattr(partition, 'fstype', '') or '').strip().lower()

    # macOS 的 APFS System Volume(/) 与 Data Volume 共用 container。
    # psutil 对 / 的 used/percent 可能只反映 sealed System Volume，
    # 但 total/free 又是共享 container 语义，导致三者无法相加。
    # Dashboard 的系统盘卡片按 container 容量展示，保证 used + free = total。
    if os_alias == 'mac' and mountpoint == '/' and fstype == 'apfs' and total > 0:
        free = max(0, min(free, total))
        used = max(0, total - free)
        percent = round((used / total) * 100.0, 1)

    return {
        'total': total,
        'used': used,
        'free': free,
        'percent': percent,
    }

def _should_include_volume(os_alias, partition) -> bool:
    mountpoint = str(partition.mountpoint or '').strip()
    fstype = str(partition.fstype or '').strip().lower()

    if os_alias == 'mac':
        return mountpoint == '/' or mountpoint.startswith('/Volumes/')

    if os_alias == 'win':
        drive_type = _windows_drive_type(mountpoint)
        return drive_type not in (0, 1, 5)

    pseudo_fs = {
        'proc', 'sysfs', 'devtmpfs', 'devfs', 'tmpfs', 'squashfs', 'overlay',
        'cgroup', 'cgroup2', 'pstore', 'securityfs', 'debugfs', 'tracefs',
    }
    return fstype not in pseudo_fs

def _volume_metadata(os_alias, partition) -> dict:
    mountpoint = str(partition.mountpoint or '').strip()
    fstype = str(partition.fstype or '').strip().lower()

    if os_alias == 'win':
        drive_type = _windows_drive_type(mountpoint)
        kind_map = {
            2: 'removable',
            3: 'local',
            4: 'network',
            6: 'ramdisk',
        }
        system_drive = str(os.environ.get('SystemDrive') or '').rstrip('\\/').casefold()
        current_drive = mountpoint.rstrip('\\/').casefold()
        label = _windows_volume_label(mountpoint)
        return {
            'name': label or mountpoint.rstrip('\\/') or mountpoint,
            'kind': kind_map.get(drive_type, 'local'),
            'system': bool(system_drive and current_drive == system_drive),
        }

    if os_alias == 'mac':
        network_fs = {'smbfs', 'nfs', 'afpfs', 'webdav'}
        if mountpoint == '/':
            return {'name': 'System Volume', 'kind': 'system', 'system': True}
        name = os.path.basename(mountpoint.rstrip('/')) or mountpoint
        return {
            'name': name,
            'kind': 'network' if fstype in network_fs else 'external',
            'system': False,
        }

    network_fs = {'nfs', 'nfs4', 'cifs', 'smbfs', 'sshfs', 'fuse.sshfs'}
    name = '/' if mountpoint == '/' else (os.path.basename(mountpoint.rstrip('/')) or mountpoint)
    return {
        'name': 'System Volume' if mountpoint == '/' else name,
        'kind': 'network' if fstype in network_fs else 'local',
        'system': mountpoint == '/',
    }

def _windows_drive_type(mountpoint: str) -> int:
    try:
        root = mountpoint
        if len(root) == 2 and root[1] == ':':
            root += '\\'
        return int(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)))
    except Exception:
        return 3

def _windows_volume_label(mountpoint: str) -> str:
    try:
        root = mountpoint
        if len(root) == 2 and root[1] == ':':
            root += '\\'
        volume_name = ctypes.create_unicode_buffer(261)
        fs_name = ctypes.create_unicode_buffer(261)
        serial = ctypes.c_ulong()
        max_component = ctypes.c_ulong()
        flags = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root),
            volume_name,
            len(volume_name),
            ctypes.byref(serial),
            ctypes.byref(max_component),
            ctypes.byref(flags),
            fs_name,
            len(fs_name),
        )
        return volume_name.value.strip() if ok else ''
    except Exception:
        return ''
