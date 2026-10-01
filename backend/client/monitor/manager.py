import ctypes
import os
import socket
import threading
import time

from core.device.local_identity import get_local_identity
from core.protocol.monitor import (
    MONITOR_DEFAULT_INTERVALS,
    MONITOR_MAX_INTERVAL_SECONDS,
    MONITOR_MIN_INTERVAL_SECONDS,
    MONITOR_SUPPORTED_CHANNELS,
    normalize_monitor_channels,
    normalize_monitor_intervals,
    normalize_monitor_options,
)
from core.protocol.message_types import (
    MSG_TYPE_MONITOR_CLOSED,
    MSG_TYPE_MONITOR_ERROR,
    MSG_TYPE_MONITOR_OPENED,
    MSG_TYPE_MONITOR_SNAPSHOT,
)


class DeviceMonitorManager:
    """
    Client 端轻量设备监控会话。

    监控数据独立于 command foreground task，只在 Server 明确打开会话后采集。
    不同 channel 使用各自采样周期，避免低频指标跟随 CPU / Network 高频刷新。
    """

    SUPPORTED_CHANNELS = MONITOR_SUPPORTED_CHANNELS
    DEFAULT_INTERVALS = MONITOR_DEFAULT_INTERVALS
    MIN_INTERVAL_SECONDS = MONITOR_MIN_INTERVAL_SECONDS
    MAX_INTERVAL_SECONDS = MONITOR_MAX_INTERVAL_SECONDS

    def __init__(self, connection):
        self.connection = connection
        self._os_alias = get_local_identity().os_alias
        self._lock = threading.RLock()
        self._sessions = {}
        self._process_service = None

    def open_session(self, monitor_session_id: str, channels=None, intervals=None, options=None):
        monitor_session_id = str(monitor_session_id or '').strip()
        if not monitor_session_id:
            return

        normalized_channels = normalize_monitor_channels(channels)
        normalized_intervals = normalize_monitor_intervals(intervals, normalized_channels)
        normalized_options = normalize_monitor_options(options)

        self.close_session(monitor_session_id, notify=False)

        item = {
            'monitor_session_id': monitor_session_id,
            'channels': normalized_channels,
            'intervals': normalized_intervals,
            'options': normalized_options,
            'stop_event': threading.Event(),
            'notify_close': True,
            'network_baseline': None,
            'process_cache': {},
            'process_cpu_primed': set(),
            'seq': 0,
        }
        worker = threading.Thread(
            target=self._run_session,
            args=(item,),
            daemon=True,
            name=f'device-monitor-{monitor_session_id[:8]}',
        )
        item['worker'] = worker

        with self._lock:
            self._sessions[monitor_session_id] = item

        worker.start()

    def update_session(self, monitor_session_id: str, channels=None, intervals=None, options=None):
        monitor_session_id = str(monitor_session_id or '').strip()
        with self._lock:
            item = self._sessions.get(monitor_session_id)
            if not item:
                return

            next_channels = normalize_monitor_channels(
                item.get('channels') if channels is None else channels
            )
            next_intervals = normalize_monitor_intervals(
                item.get('intervals') if intervals is None else intervals,
                next_channels,
            )
            item['channels'] = next_channels
            item['intervals'] = next_intervals
            if options is not None:
                previous_pid = self._read_process_pid_option(item)
                item['options'] = normalize_monitor_options(options)
                if self._read_process_pid_option(item) != previous_pid:
                    item['process_cache'] = {}
                    item['process_cpu_primed'] = set()

    def close_session(self, monitor_session_id: str, notify: bool = True):
        monitor_session_id = str(monitor_session_id or '').strip()
        with self._lock:
            item = self._sessions.get(monitor_session_id)
            if not item:
                return
            if not notify:
                item['notify_close'] = False
            item['stop_event'].set()

    def close_all_sessions(self, notify: bool = False):
        with self._lock:
            items = list(self._sessions.values())
            for item in items:
                if not notify:
                    item['notify_close'] = False
                item['stop_event'].set()

    def _run_session(self, item: dict):
        monitor_session_id = item['monitor_session_id']
        try:
            import psutil

            # cpu_percent / network rate 都需要前一帧基线，启动时先预热一次。
            psutil.cpu_percent(interval=None)
            item['network_baseline'] = self._read_network_baseline(psutil)

            self._send({
                'type': MSG_TYPE_MONITOR_OPENED,
                'monitor_session_id': monitor_session_id,
                'channels': list(item.get('channels') or []),
                'intervals': dict(item.get('intervals') or {}),
            })

            now = time.monotonic()
            next_due = {}
            for channel in item.get('channels') or []:
                if channel in (
                    'storage',
                    'battery',
                    'processes',
                    'apps',
                    'process_detail',
                    'process_connections',
                    'process_open_files',
                ):
                    next_due[channel] = now
                else:
                    next_due[channel] = now + float(item['intervals'].get(channel, 0.5))

            while not item['stop_event'].is_set():
                with self._lock:
                    channels = list(item.get('channels') or [])
                    intervals = dict(item.get('intervals') or {})

                now = time.monotonic()
                for channel in channels:
                    if channel not in next_due:
                        next_due[channel] = now
                    if now < next_due[channel]:
                        continue

                    data = self._collect_channel(channel, psutil, item)

                    # 某些 collector（例如 macOS Apps 的 System Events）可能阻塞数秒。
                    # 采集期间如果前端已经切换 channel，就丢弃这条晚到 snapshot，
                    # 避免旧 channel 的结果或瞬时错误在切换后继续影响当前页面。
                    with self._lock:
                        current_channels = list(item.get('channels') or [])
                        current_intervals = dict(item.get('intervals') or {})
                    if item['stop_event'].is_set() or channel not in current_channels:
                        next_due.pop(channel, None)
                        continue

                    item['seq'] += 1
                    self._send({
                        'type': MSG_TYPE_MONITOR_SNAPSHOT,
                        'monitor_session_id': monitor_session_id,
                        'seq': item['seq'],
                        'channel': channel,
                        'data': data,
                        'collected_at': time.time(),
                    })
                    # 从本次采集完成后重新计算周期。耗时 collector 超时/变慢后
                    # 不应因为旧 due time 已经过期而立即连续重试。
                    next_due[channel] = time.monotonic() + float(
                        current_intervals.get(channel, intervals.get(channel, 1.0))
                    )

                for channel in list(next_due.keys()):
                    if channel not in channels:
                        next_due.pop(channel, None)

                item['stop_event'].wait(0.05)

        except Exception as e:
            self._send_safely({
                'type': MSG_TYPE_MONITOR_ERROR,
                'monitor_session_id': monitor_session_id,
                'message': str(e) or 'Device monitor failed',
            })
        finally:
            with self._lock:
                current = self._sessions.get(monitor_session_id)
                notify_close = bool(current.get('notify_close')) if current else bool(item.get('notify_close'))
                self._sessions.pop(monitor_session_id, None)

            if notify_close:
                self._send_safely({
                    'type': MSG_TYPE_MONITOR_CLOSED,
                    'monitor_session_id': monitor_session_id,
                })

    def _collect_channel(self, channel: str, psutil, item: dict) -> dict:
        if channel == 'system':
            return self._collect_system(psutil)
        if channel == 'storage':
            return self._collect_storage(psutil)
        if channel == 'network':
            return self._collect_network(psutil, item)
        if channel == 'battery':
            return self._collect_battery(psutil)
        if channel == 'processes':
            return self._collect_processes()
        if channel == 'apps':
            return self._collect_apps()
        if channel == 'process_detail':
            return self._collect_process_detail(psutil, item)
        if channel == 'process_connections':
            return self._collect_process_connections(psutil, item)
        if channel == 'process_open_files':
            return self._collect_process_open_files(psutil, item)
        return {}

    def _get_process_service(self):
        if self._process_service is None:
            from client.commands.common.services.process.process_service import ProcessService
            self._process_service = ProcessService(self)
        return self._process_service

    def _collect_processes(self) -> dict:
        try:
            return {'items': self._get_process_service().list_processes() or []}
        except Exception as e:
            return {'items': [], 'error': str(e) or 'Failed to list processes'}

    def _collect_apps(self) -> dict:
        service = self._get_process_service()
        try:
            if self._os_alias == 'win':
                items = service.list_windows_apps()
            elif self._os_alias == 'mac':
                items = service.list_macos_app()
            else:
                raise Exception('Unsupported os:' + str(self._os_alias))
            return {'items': items or []}
        except Exception as e:
            return {'items': [], 'error': str(e) or 'Failed to list applications'}

    def _read_process_pid_option(self, item: dict) -> int:
        options = item.get('options') if isinstance(item.get('options'), dict) else {}
        try:
            pid = int(options.get('pid') or 0)
        except Exception:
            pid = 0
        return pid

    def _resolve_process_pid(self, item: dict) -> int:
        pid = self._read_process_pid_option(item)
        if pid <= 0:
            raise ValueError('Process monitor requires a valid pid')
        return pid

    def _get_monitored_process(self, psutil, item: dict):
        pid = self._resolve_process_pid(item)
        cache = item.setdefault('process_cache', {})
        proc = cache.get(pid)
        if proc is None:
            proc = psutil.Process(pid)
            cache.clear()
            cache[pid] = proc
        return pid, proc

    def _collect_process_detail(self, psutil, item: dict) -> dict:
        pid, proc = self._get_monitored_process(psutil, item)
        data = self._get_process_service().get_process_basic_detail(pid, proc=proc)

        # psutil 的进程 CPU 百分比需要前一帧作为基线，第一帧不展示伪 0%。
        primed = item.setdefault('process_cpu_primed', set())
        if pid not in primed:
            primed.add(pid)
            data['cpu_percent'] = None
        return data

    def _collect_process_connections(self, psutil, item: dict) -> dict:
        pid, proc = self._get_monitored_process(psutil, item)
        return {
            'pid': pid,
            'items': self._get_process_service().get_process_connections(pid, proc=proc),
        }

    def _collect_process_open_files(self, psutil, item: dict) -> dict:
        pid, proc = self._get_monitored_process(psutil, item)
        return {
            'pid': pid,
            'items': self._get_process_service().get_process_open_files(pid, proc=proc),
        }

    def _collect_system(self, psutil) -> dict:
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        uptime_seconds = max(0.0, time.time() - float(psutil.boot_time()))

        cpu_percent = round(float(psutil.cpu_percent(interval=None)), 1)

        # macOS 下 psutil 的非阻塞 CPU 采样偶尔会出现单帧 0.0。
        # 仅过滤孤立的 0% 毛刺；如果连续两帧都是 0%，则按真实 0% 显示。
        if self._os_alias == 'mac':
            now = time.monotonic()
            state = getattr(self, '_mac_cpu_deglitch_state', None)

            if not isinstance(state, dict):
                state = {
                    'last_valid': None,
                    'last_valid_at': 0.0,
                    'zero_pending': False,
                }
                self._mac_cpu_deglitch_state = state

            if cpu_percent == 0.0:
                last_valid = state.get('last_valid')
                last_valid_at = float(state.get('last_valid_at') or 0.0)
                last_valid_age = now - last_valid_at

                if (
                        not state.get('zero_pending')
                        and last_valid is not None
                        and float(last_valid) > 0.0
                        and last_valid_age <= 1.5
                ):
                    cpu_percent = float(last_valid)
                    state['zero_pending'] = True
                else:
                    state['zero_pending'] = True
            else:
                state['last_valid'] = cpu_percent
                state['last_valid_at'] = now
                state['zero_pending'] = False

        return {
            'cpu_percent': cpu_percent,
            'cpu_count': int(psutil.cpu_count(logical=True) or 0),
            'memory': {
                'total': int(memory.total or 0),
                'used': int(memory.used or 0),
                'available': int(memory.available or 0),
                'percent': round(float(memory.percent or 0), 1),
            },
            'swap': {
                'total': int(swap.total or 0),
                'used': int(swap.used or 0),
                'free': int(swap.free or 0),
                'percent': round(float(swap.percent or 0), 1),
            },
            'uptime_seconds': int(uptime_seconds),
            'process_count': len(psutil.pids()),
        }

    # def _collect_system(self, psutil) -> dict:
    #     memory = psutil.virtual_memory()
    #     swap = psutil.swap_memory()
    #     uptime_seconds = max(0.0, time.time() - float(psutil.boot_time()))
    #
    #     return {
    #         'cpu_percent': round(float(psutil.cpu_percent(interval=None)), 1),
    #         'cpu_count': int(psutil.cpu_count(logical=True) or 0),
    #         'memory': {
    #             'total': int(memory.total or 0),
    #             'used': int(memory.used or 0),
    #             'available': int(memory.available or 0),
    #             'percent': round(float(memory.percent or 0), 1),
    #         },
    #         'swap': {
    #             'total': int(swap.total or 0),
    #             'used': int(swap.used or 0),
    #             'free': int(swap.free or 0),
    #             'percent': round(float(swap.percent or 0), 1),
    #         },
    #         'uptime_seconds': int(uptime_seconds),
    #         'process_count': len(psutil.pids()),
    #     }

    def _collect_storage(self, psutil) -> dict:
        volumes = []
        seen_mounts = set()

        for partition in psutil.disk_partitions(all=False):
            mountpoint = str(partition.mountpoint or '').strip()
            if not mountpoint or mountpoint in seen_mounts:
                continue
            if not self._should_include_volume(partition):
                continue

            seen_mounts.add(mountpoint)
            try:
                usage = psutil.disk_usage(mountpoint)
            except Exception:
                continue

            meta = self._volume_metadata(partition)
            normalized_usage = self._normalize_volume_usage(partition, usage)
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
        return {'volumes': volumes}

    def _normalize_volume_usage(self, partition, usage) -> dict:
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
        if self._os_alias == 'mac' and mountpoint == '/' and fstype == 'apfs' and total > 0:
            free = max(0, min(free, total))
            used = max(0, total - free)
            percent = round((used / total) * 100.0, 1)

        return {
            'total': total,
            'used': used,
            'free': free,
            'percent': percent,
        }

    def _collect_network(self, psutil, item: dict) -> dict:
        now = time.monotonic()
        counters = psutil.net_io_counters()
        current = (
            int(getattr(counters, 'bytes_recv', 0) or 0),
            int(getattr(counters, 'bytes_sent', 0) or 0),
            now,
        )
        previous = item.get('network_baseline')
        item['network_baseline'] = current

        rx_per_sec = 0.0
        tx_per_sec = 0.0
        if previous:
            elapsed = max(current[2] - float(previous[2]), 0.001)
            rx_per_sec = max(0.0, (current[0] - int(previous[0])) / elapsed)
            tx_per_sec = max(0.0, (current[1] - int(previous[1])) / elapsed)

        interface_name, ipv4 = self._find_active_interface(psutil)
        return {
            'rx_bytes_per_sec': int(rx_per_sec),
            'tx_bytes_per_sec': int(tx_per_sec),
            'bytes_received': current[0],
            'bytes_sent': current[1],
            'interface': interface_name,
            'ipv4': ipv4,
        }

    def _collect_battery(self, psutil) -> dict:
        try:
            battery = psutil.sensors_battery()
        except Exception:
            battery = None

        if battery is None:
            return {'available': False}

        return {
            'available': True,
            'percent': round(float(battery.percent or 0), 1),
            'plugged': bool(battery.power_plugged),
            'seconds_left': self._normalize_battery_seconds_left(
                getattr(battery, 'secsleft', None),
                psutil,
            ),
        }

    def _read_network_baseline(self, psutil):
        try:
            counters = psutil.net_io_counters()
            return (
                int(getattr(counters, 'bytes_recv', 0) or 0),
                int(getattr(counters, 'bytes_sent', 0) or 0),
                time.monotonic(),
            )
        except Exception:
            return None

    def _find_active_interface(self, psutil):
        try:
            all_stats = psutil.net_if_stats()
            all_addrs = psutil.net_if_addrs()
        except Exception:
            return '', ''

        fallback = ('', '')
        for name, addresses in all_addrs.items():
            stats = all_stats.get(name)
            if stats is not None and not stats.isup:
                continue

            ipv4 = ''
            for addr in addresses:
                if getattr(addr, 'family', None) == socket.AF_INET:
                    candidate = str(getattr(addr, 'address', '') or '').strip()
                    if candidate:
                        ipv4 = candidate
                        break

            if not ipv4:
                continue
            if ipv4.startswith('127.'):
                if not fallback[0]:
                    fallback = (name, ipv4)
                continue
            return name, ipv4

        return fallback

    def _should_include_volume(self, partition) -> bool:
        mountpoint = str(partition.mountpoint or '').strip()
        fstype = str(partition.fstype or '').strip().lower()

        if self._os_alias == 'mac':
            return mountpoint == '/' or mountpoint.startswith('/Volumes/')

        if self._os_alias == 'win':
            drive_type = self._windows_drive_type(mountpoint)
            return drive_type not in (0, 1, 5)

        pseudo_fs = {
            'proc', 'sysfs', 'devtmpfs', 'devfs', 'tmpfs', 'squashfs', 'overlay',
            'cgroup', 'cgroup2', 'pstore', 'securityfs', 'debugfs', 'tracefs',
        }
        return fstype not in pseudo_fs

    def _volume_metadata(self, partition) -> dict:
        mountpoint = str(partition.mountpoint or '').strip()
        fstype = str(partition.fstype or '').strip().lower()

        if self._os_alias == 'win':
            drive_type = self._windows_drive_type(mountpoint)
            kind_map = {
                2: 'removable',
                3: 'local',
                4: 'network',
                6: 'ramdisk',
            }
            system_drive = str(os.environ.get('SystemDrive') or '').rstrip('\\/').casefold()
            current_drive = mountpoint.rstrip('\\/').casefold()
            label = self._windows_volume_label(mountpoint)
            return {
                'name': label or mountpoint.rstrip('\\/') or mountpoint,
                'kind': kind_map.get(drive_type, 'local'),
                'system': bool(system_drive and current_drive == system_drive),
            }

        if self._os_alias == 'mac':
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

    def _windows_drive_type(self, mountpoint: str) -> int:
        if self._os_alias != 'win':
            return 0
        try:
            root = mountpoint
            if len(root) == 2 and root[1] == ':':
                root += '\\'
            return int(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)))
        except Exception:
            return 3

    def _windows_volume_label(self, mountpoint: str) -> str:
        if self._os_alias != 'win':
            return ''
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

    def _normalize_battery_seconds_left(self, value, psutil):
        try:
            seconds = int(value)
        except Exception:
            return None

        unknown_values = {
            int(getattr(psutil, 'POWER_TIME_UNKNOWN', -2)),
            int(getattr(psutil, 'POWER_TIME_UNLIMITED', -1)),
        }
        if seconds < 0 or seconds in unknown_values:
            return None
        return seconds

    def _send(self, payload: dict):
        self.connection.send(payload)

    def _send_safely(self, payload: dict):
        try:
            self._send(payload)
        except Exception:
            pass
