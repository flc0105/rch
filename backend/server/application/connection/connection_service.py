from datetime import datetime

from core.utils.datetime_utils import parse_iso_datetime
from core.client_revision import build_client_revision_manifest
from server.connection.client_session import ClientSession
from server.connection.transport.client_transport import ClientTransport


class WebConnectionService:
    """
    Web 连接服务。

    职责：
    - 序列化连接信息
    - 创建带 Web 能力的客户端会话对象
    - 处理连接上线/下线/心跳状态事件
    - 维护最近见过的设备缓存
    """

    STALE_AFTER_SECONDS = 45

    def __init__(
        self,
        server,
        event_bus,
        artifact_service,
        recent_device_store=None,
        connection_history_store=None,
        script_grant_service=None,
    ):
        self.server = server
        self.event_bus = event_bus
        self.artifact_service = artifact_service
        self.recent_device_store = recent_device_store
        self.connection_history_store = connection_history_store
        self.script_grant_service = script_grant_service

    def _now(self):
        return datetime.now()

    def _build_connection_state(self, session: ClientSession) -> str:
        disconnected_at = parse_iso_datetime(session.context.disconnected_at)
        if disconnected_at is not None:
            return 'offline'

        last_seen_at = parse_iso_datetime(session.context.last_seen_at)
        if last_seen_at is None:
            return 'online'

        age_seconds = max((self._now() - last_seen_at).total_seconds(), 0)
        if age_seconds > self.STALE_AFTER_SECONDS:
            return 'stale'

        return 'online'

    def _machine_key(self, machine_id: str) -> str:
        return str(machine_id or '').strip().lower()


    def _get_revision_state(self, client_revision: str, server_revision: str) -> str:
        client_revision_text = str(client_revision or '').strip()
        server_revision_text = str(server_revision or '').strip()
        if not client_revision_text or not server_revision_text:
            return 'unknown'
        if client_revision_text == server_revision_text:
            return 'current'
        return 'outdated'

    def _build_changed_revision_files(self, client_files: dict, server_files: dict) -> list[dict]:
        if not client_files or not server_files:
            return []

        results = []
        all_paths = sorted(set(client_files.keys()) | set(server_files.keys()))
        for relative_path in all_paths:
            client_digest = str(client_files.get(relative_path) or '')
            server_digest = str(server_files.get(relative_path) or '')
            if client_digest == server_digest:
                continue

            if relative_path not in client_files:
                change_type = 'added'
            elif relative_path not in server_files:
                change_type = 'removed'
            else:
                change_type = 'modified'

            results.append({
                'path': relative_path,
                'change': change_type,
            })
        return results

    def _decorate_connection_with_client_revision(self, payload: dict, server_manifest: dict = None) -> dict:
        if not isinstance(payload, dict):
            return payload

        result = dict(payload)
        if str(result.get('connection_state') or '').strip() != 'online':
            result['client_revision_state'] = ''
            return result

        if not isinstance(server_manifest, dict):
            return result

        server_revision = str(server_manifest.get('revision') or '')
        result['client_revision_state'] = self._get_revision_state(
            result.get('client_revision'),
            server_revision,
        )
        return result

    def _decorate_connection_with_device_view_prefs(self, payload: dict, server_manifest: dict = None) -> dict:
        if not isinstance(payload, dict):
            return payload

        result = self._decorate_connection_with_client_revision(payload, server_manifest=server_manifest)
        if not self.recent_device_store:
            result.setdefault('machine_alias', '')
            result.setdefault('device_alias', '')
            result.setdefault('device_hidden', False)
            result.setdefault('device_hidden_by_client', False)
            result.setdefault('device_hidden_by_machine', False)
            return result

        prefs = self.recent_device_store.get_device_view_prefs(
            client_id=result.get('client_id') or '',
            machine_id=result.get('machine_id') or '',
        )
        result.update(prefs)
        return result

    # ------------------ payload ------------------ #
    def serialize_connection(self, session: ClientSession) -> dict:
        info = session.session_info
        return {
            'client_id': info.client_id,
            'addr': info.addr,
            'hostname': info.hostname,
            'machine_id': info.machine_id,
            # 'machine_id_version': info.machine_id_version,
            'machine_fingerprint_basis': info.machine_fingerprint_basis,
            'os_type': info.os_type,
            'os_alias': info.os_alias,
            'os_ver': info.os_ver,
            'os_name': info.os_name,
            'os_full': info.os_full,
            'arch': info.arch,
            'manufacturer': info.manufacturer,
            'model': info.model,
            'integrity': info.integrity,
            'cwd': info.cwd,
            'connected_at': session.context.connected_at,
            'disconnected_at': session.context.disconnected_at,
            'last_seen_at': session.context.last_seen_at,
            'last_heartbeat_sent_at': session.context.last_heartbeat_sent_at,
            'last_heartbeat_ack_at': session.context.last_heartbeat_ack_at,
            'last_rtt_ms': session.context.last_rtt_ms,
            'stale_after_seconds': self.STALE_AFTER_SECONDS,
            'connection_state': self._build_connection_state(session),
            'build_version': info.build_version,
            'client_revision': info.client_revision,
            'client_revision_parts': dict(info.client_revision_parts),
            'python_ver': info.get_extra('python_ver'),
            'process_id': info.get_extra('process_id'),
            'launch_command': info.get_extra('launch_command'),
            'username': info.get_extra('username'),
            'process_name': info.get_extra('process_name'),
            'http_transfer_mode': info.get_extra('http_transfer_mode'),
            'python_execution_mode': info.get_extra('python_execution_mode'),
            'remote_watchdog_enabled': info.get_extra('remote_watchdog_enabled'),
            'local_watchdog_enabled': info.get_extra('local_watchdog_enabled'),
            'variable_manifest': list(info.get_extra('variable_manifest') or []),
        }

    def _sync_recent_online_connections(self, active_connections: list[dict]):
        if not self.recent_device_store:
            return

        for item in active_connections:
            machine_id = str(item.get('machine_id') or '').strip()
            if not machine_id:
                continue
            self.recent_device_store.upsert_from_connection(item)

    def _build_recent_offline_entries(self, active_connections: list[dict]) -> list[dict]:
        if not self.recent_device_store:
            return []

        active_machine_ids = {
            self._machine_key(item.get('machine_id'))
            for item in active_connections
            if str(item.get('machine_id') or '').strip()
        }

        results = []
        for item in self.recent_device_store.list_recent_devices():
            machine_key = self._machine_key(item.get('machine_id'))
            if not machine_key:
                continue
            if machine_key in active_machine_ids:
                continue

            offline_item = {
                'client_id': item.get('client_id') or '',
                'addr': item.get('addr') or '',
                'hostname': item.get('hostname') or 'Unknown',
                'machine_id': item.get('machine_id') or '',
                # 'machine_id_version': item.get('machine_id_version') or '',
                'machine_fingerprint_basis': item.get('machine_fingerprint_basis') or '',
                'os_type': item.get('os_type') or 'Unknown',
                'os_alias': item.get('os_alias') or 'unknown',
                'os_ver': item.get('os_ver') or 'Unknown',

                'os_name': item.get('os_name') or 'Unknown',
                'os_full': item.get('os_full') or 'Unknown',
                'arch': item.get('arch') or 'Unknown',
                'manufacturer': item.get('manufacturer') or 'Unknown',
                'model': item.get('model') or 'Unknown',

                'integrity': item.get('integrity') or '?',
                'cwd': item.get('cwd') or '',
                'connected_at': item.get('connected_at') or '',
                'disconnected_at': item.get('disconnected_at') or '',
                'last_seen_at': item.get('last_seen_at') or '',
                'last_heartbeat_sent_at': item.get('last_heartbeat_sent_at') or '',
                'last_heartbeat_ack_at': item.get('last_heartbeat_ack_at') or '',
                'last_rtt_ms': item.get('last_rtt_ms'),
                'stale_after_seconds': item.get('stale_after_seconds') or self.STALE_AFTER_SECONDS,
                'connection_state': 'offline',
                'build_version': item.get('build_version') or '',
                'client_revision': item.get('client_revision') or '',
                'client_revision_parts': dict(item.get('client_revision_parts')) if isinstance(item.get('client_revision_parts'), dict) else {},
                'python_ver': item.get('python_ver') or '',
                'process_id': item.get('process_id') or '',
                'launch_command': item.get('launch_command') or '',
                'username': item.get('username') or '',
                'process_name': item.get('process_name') or '',
                'http_transfer_mode': item.get('http_transfer_mode') or '',
                'python_execution_mode': item.get('python_execution_mode') or '',
                'remote_watchdog_enabled': item.get('remote_watchdog_enabled'),
                'local_watchdog_enabled': item.get('local_watchdog_enabled'),
                'recent_cached': True,
            }
            results.append(self._decorate_connection_with_device_view_prefs(offline_item))

        return results

    def get_system_paths(self, client_id: str):
        session = self.server.get_target_connection_by_client_id(str(client_id or '').strip())
        return session.session_info.system_paths

    def get_client_revision_status(self, client_id: str) -> dict:
        client_id_text = str(client_id or '').strip()
        if not client_id_text:
            raise ValueError('Invalid client id')

        session = self.server.get_target_connection_by_client_id(client_id_text)
        connection_state = self._build_connection_state(session)
        if connection_state != 'online':
            return {
                'client_id': client_id_text,
                'state': 'offline',
                'changed_files': [],
                'changed_files_available': False,
            }

        # 每次查询都基于当前磁盘源码重新计算，Server 无需重启即可反映最新 revision。
        server_manifest = build_client_revision_manifest(include_parts=False, include_files=True)
        info = session.session_info
        client_revision = str(info.client_revision or '').strip()
        server_revision = str(server_manifest.get('revision') or '').strip()
        revision_state = self._get_revision_state(client_revision, server_revision)
        client_files = dict(info.client_revision_files or {})
        server_files = dict(server_manifest.get('files') or {})
        changed_files_available = bool(client_files)
        changed_files = []
        if revision_state == 'outdated' and changed_files_available:
            changed_files = self._build_changed_revision_files(client_files, server_files)

        return {
            'client_id': client_id_text,
            'state': revision_state,
            'current_revision': client_revision,
            'server_revision': server_revision,
            'changed_files': changed_files,
            'changed_files_available': changed_files_available,
        }

    def get_connections_payload(self):
        active_connections = [self.serialize_connection(session) for session in self.server.connections.all()]
        self._sync_recent_online_connections(active_connections)
        server_manifest = build_client_revision_manifest(include_parts=False, include_files=False) if active_connections else {}
        active_connections = [
            self._decorate_connection_with_device_view_prefs(item, server_manifest=server_manifest)
            for item in active_connections
        ]
        recent_offline = self._build_recent_offline_entries(active_connections)
        return active_connections + recent_offline

    def get_machine_connection_history(self, machine_id: str) -> dict:
        machine_id_text = str(machine_id or '').strip()
        if not machine_id_text:
            raise ValueError('Invalid machine id')

        # 查询前同步仍在线 session，保证在线时长和最后活动时间尽量新。
        if self.connection_history_store:
            active_client_ids = set()
            for session in self.server.connections.all():
                session_machine_id = str(getattr(session.session_info, 'machine_id', '') or '').strip()
                if self._machine_key(session_machine_id) != self._machine_key(machine_id_text):
                    continue

                client_id = str(getattr(session.session_info, 'client_id', '') or '').strip()
                if client_id:
                    active_client_ids.add(client_id)
                self.connection_history_store.record_heartbeat(self.serialize_connection(session))

            self.connection_history_store.reconcile_active_sessions(machine_id_text, active_client_ids)
            lifecycle_payload = self.connection_history_store.get_history(machine_id_text)
        else:
            lifecycle_payload = {
                'machine_id': machine_id_text,
                'tracking_started_at': '',
                'sessions': [],
            }

        command_counts = self.server.command_history.view_service.get_connection_command_counts_by_machine_id(machine_id_text)
        unassigned_command_count = int(command_counts.get('', 0) or 0)

        sessions = []
        total_online_duration_ms = 0
        online_session_count = 0

        for session in lifecycle_payload.get('sessions') or []:
            copied = dict(session)
            client_id = str(copied.get('client_id') or '').strip()
            copied['command_count'] = int(command_counts.get(client_id, 0) or 0)

            duration_ms = int(copied.get('duration_ms', 0) or 0)
            total_online_duration_ms += duration_ms
            if copied.get('connection_state') == 'online':
                online_session_count += 1

            sessions.append(copied)

        def _session_sort_value(item):
            value = item.get('connected_at') or ''
            return parse_iso_datetime(value) or datetime.min

        sessions.sort(key=_session_sort_value, reverse=True)

        return {
            'machine_id': machine_id_text,
            'tracking_started_at': lifecycle_payload.get('tracking_started_at') or '',
            'connection_count': len(sessions),
            'online_connection_count': online_session_count,
            'command_count': sum(int(value or 0) for value in command_counts.values()),
            'total_online_duration_ms': total_online_duration_ms,
            'unassigned_command_count': unassigned_command_count,
            'sessions': sessions,
        }

    def get_machine_connection_commands(
        self,
        machine_id: str,
        client_id: str,
        *,
        limit=None,
        cursor: str = '',
    ) -> dict:
        return self.server.command_history.view_service.get_connection_command_page(
            machine_id,
            client_id,
            limit=limit,
            cursor=cursor,
        )

    def remove_connection(self, client_id: str, machine_id: str = '') -> dict:
        target_client_id = str(client_id or '').strip()
        target_machine_id = str(machine_id or '').strip()

        if not target_client_id:
            raise ValueError('Invalid client id')

        session = None
        was_online = False

        try:
            session = self.server.connections.get_by_client_id(target_client_id)
            was_online = True
        except Exception:
            session = None

        if session is not None:
            try:
                payload = self.serialize_connection(session)
                target_machine_id = target_machine_id or str(payload.get('machine_id') or '').strip()
            except Exception:
                pass

        recent_result = {
            'removed_count': 0,
            'removed_keys': [],
        }

        if self.recent_device_store:
            recent_result = self.recent_device_store.remove_by_identity(
                client_id=target_client_id,
                machine_id=target_machine_id,
            )

        if session is not None:
            try:
                session.send_command('kill')
            except Exception:
                pass

            try:
                session.close()
            except Exception:
                pass

            try:
                self.server.connections.remove(session)
            except Exception:
                pass

            try:
                self.event_bus.publish('connection_removed', {
                    'client_id': target_client_id,
                    'machine_id': target_machine_id,
                    'time': datetime.now().isoformat(),
                })
            except Exception:
                pass

        return {
            'client_id': target_client_id,
            'machine_id': target_machine_id,
            'was_online': was_online,
            'recent_removed_count': recent_result.get('removed_count', 0),
            'recent_removed_keys': recent_result.get('removed_keys', []),
        }


    def update_connection_device_view_prefs(self, client_id: str = '', machine_id: str = '', patch: dict = None) -> dict:
        if not self.recent_device_store:
            raise ValueError('Recent device store is unavailable')

        prefs = self.recent_device_store.update_device_view_prefs(
            client_id=client_id,
            machine_id=machine_id,
            patch=patch or {},
        )

        try:
            self.event_bus.publish('connection_device_view_prefs_updated', {
                'client_id': str(client_id or '').strip(),
                'machine_id': str(machine_id or '').strip(),
                'prefs': prefs,
                'time': datetime.now().isoformat(),
            })
        except Exception:
            pass

        return prefs

    # ------------------ connection lifecycle ------------------ #
    def create_web_connection(self, transport: ClientTransport, addr, info: dict) -> ClientSession:
        session = ClientSession(transport, info)
        session.context.command_history = self.server.command_history
        session.context.command_history_orchestrator = self.server.command_history_orchestrator
        session.context.artifact_service = self.artifact_service
        session.context.script_grant_service = self.script_grant_service

        session.context.on_unexpected_message = (
            lambda status, text, end: self.publish_background_message(session, status, text, end)
        )
        session.context.on_heartbeat_updated = (
            lambda current_session: self.publish_connection_heartbeat(current_session)
        )
        terminal_service = self.server.web_service.terminal_api.pty_session_service
        session.context.on_pty_opened = terminal_service.handle_client_opened
        session.context.on_pty_output = terminal_service.handle_client_output
        session.context.on_pty_closed = terminal_service.handle_client_closed
        session.context.on_pty_error = terminal_service.handle_client_error

        screen_view_service = self.server.web_service.screen_view_api.screen_view_session_service
        session.context.on_screen_opened = screen_view_service.handle_client_opened
        session.context.on_screen_frame = screen_view_service.handle_client_frame
        session.context.on_screen_closed = screen_view_service.handle_client_closed
        session.context.on_screen_error = screen_view_service.handle_client_error
        session.context.on_screen_input_error = screen_view_service.handle_client_input_error

        clipboard_service = self.server.web_service.clipboard_api.clipboard_session_service
        session.context.on_clipboard_result = (
            lambda data: clipboard_service.handle_client_result(session.session_info.client_id, data)
        )

        monitor_service = self.server.web_service.device_monitor_api.device_monitor_session_service
        session.context.on_monitor_opened = monitor_service.handle_client_opened
        session.context.on_monitor_snapshot = monitor_service.handle_client_snapshot
        session.context.on_monitor_error = monitor_service.handle_client_error
        session.context.on_monitor_closed = monitor_service.handle_client_closed

        transfer_service = self.server.web_service.transfer_api.transfer_service
        session.context.on_transfer_update = (
            lambda data: transfer_service.handle_client_update(session.session_info.client_id, data)
        )
        return session

    def handle_connection_registered(self, session: ClientSession):
        session.services.heartbeat_service.mark_connected()
        payload = self.serialize_connection(session)
        if self.recent_device_store:
            self.recent_device_store.upsert_from_connection(payload)
        if self.connection_history_store:
            self.connection_history_store.record_connected(payload)
        self.publish_connection_online(session)

    def handle_connection_closed(self, session: ClientSession):
        session.services.heartbeat_service.mark_disconnected()
        payload = self.serialize_connection(session)
        if self.recent_device_store:
            self.recent_device_store.upsert_from_connection(payload)
            self.recent_device_store.mark_offline(
                machine_id=payload.get('machine_id') or '',
                disconnected_at=payload.get('disconnected_at') or '',
            )
        if self.connection_history_store:
            self.connection_history_store.record_disconnected(payload)
        try:
            if self.script_grant_service is not None:
                self.script_grant_service.revoke_by_client(session.session_info.client_id)
        except Exception:
            pass
        try:
            self.server.web_service.terminal_api.pty_session_service.handle_client_disconnected(
                session.session_info.client_id
            )
        except Exception:
            pass
        try:
            self.server.web_service.screen_view_api.screen_view_session_service.handle_client_disconnected(
                session.session_info.client_id
            )
        except Exception:
            pass
        try:
            self.server.web_service.clipboard_api.clipboard_session_service.handle_client_disconnected(
                session.session_info.client_id
            )
        except Exception:
            pass
        try:
            self.server.web_service.device_monitor_api.device_monitor_session_service.handle_client_disconnected(
                session.session_info.client_id
            )
        except Exception:
            pass
        try:
            self.server.web_service.transfer_api.handle_client_disconnected(
                session.session_info.client_id
            )
        except Exception:
            pass
        self.publish_connection_offline(session)

    # ------------------ event publish ------------------ #
    def publish_connection_online(self, session: ClientSession):
        server_manifest = build_client_revision_manifest(include_parts=False, include_files=False)
        self.event_bus.publish('connection_online', {
            'connection': self._decorate_connection_with_device_view_prefs(
                self.serialize_connection(session),
                server_manifest=server_manifest,
            ),
            'time': datetime.now().isoformat()
        })

    def publish_connection_offline(self, session: ClientSession):
        self.event_bus.publish('connection_offline', {
            'client_id': session.session_info.client_id,
            'connection': self._decorate_connection_with_device_view_prefs(self.serialize_connection(session)),
            'time': datetime.now().isoformat()
        })

    def publish_connection_heartbeat(self, session: ClientSession):
        payload = self.serialize_connection(session)
        if self.recent_device_store:
            self.recent_device_store.upsert_from_connection(payload)
        if self.connection_history_store:
            self.connection_history_store.record_heartbeat(payload)

        self.event_bus.publish('connection_heartbeat', {
            'connection': self._decorate_connection_with_device_view_prefs(payload),
            'time': datetime.now().isoformat()
        })

    def publish_background_message(self, session: ClientSession, status, text, end):
        self.event_bus.publish('background_message', {
            'client_id': session.session_info.client_id,
            'status': status,
            'text': text,
            'eof': end,
            'time': datetime.now().isoformat()
        })

    def publish_file_received(self, client_id: str, artifact_info: dict):
        if not isinstance(artifact_info, dict):
            return

        self.event_bus.publish('file_received', {
            'client_id': client_id,
            'artifact_id': artifact_info.get('artifact_id', ''),
            'artifact_type': artifact_info.get('artifact_type', ''),
            'category': artifact_info.get('category', ''),
            'hostname': artifact_info.get('hostname', ''),
            'machine_id': artifact_info.get('machine_id', ''),
            'original_name': artifact_info.get('original_name', ''),
            'stored_name': artifact_info.get('stored_name', ''),
            'size': artifact_info.get('size', 0),
            'created_at': artifact_info.get('created_at', ''),
            'download_url': artifact_info.get('download_url', ''),
            'preview_url': artifact_info.get('preview_url', ''),
        })
