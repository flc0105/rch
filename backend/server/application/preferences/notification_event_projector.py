from datetime import datetime, timezone


class NotificationEventProjector:
    """Project notification-worthy server events into durable notification history."""

    SUPPORTED_EVENTS = {
        'server_cleanup_completed',
        'external_tool_lifecycle',
        'agent_build_lifecycle',
        'file_transfer_lifecycle',
        'connection_online',
        'connection_offline',
        'background_job_lifecycle',
        'pty_lifecycle',
        'screen_view_lifecycle',
        'artifact_created',
        'device_event',
    }

    def __init__(self, *, history_store, server):
        self.history_store = history_store
        self.server = server

    def record_event(self, event_type: str, payload: dict, event_id: str, target_tab_id: str = ''):
        del target_tab_id
        normalized_type = str(event_type or '').strip()
        if normalized_type not in self.SUPPORTED_EVENTS:
            return None

        builder = getattr(self, f'_build_{normalized_type}', None)
        if builder is None:
            return None
        notification = builder(payload if isinstance(payload, dict) else {})
        if not notification:
            return None

        notification['event_id'] = str(event_id or '').strip()
        notification['shown_at'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        stored, created = self.history_store.add_notification(notification)
        return stored if created else None

    def _build_server_cleanup_completed(self, payload):
        removed_files = int(payload.get('removed_files') or 0)
        removed_records = int(payload.get('removed_records') or 0)
        bytes_freed = int(payload.get('bytes_freed') or 0)
        error_count = int(payload.get('error_count') or 0)
        message_parts = [
            f'{removed_files} file{"" if removed_files == 1 else "s"}',
            f'{removed_records} record{"" if removed_records == 1 else "s"}',
            self._format_bytes(bytes_freed),
        ]
        if error_count:
            message_parts.append(f'{error_count} error{"" if error_count == 1 else "s"}')
        log_url = str(payload.get('log_url') or '').strip()
        actions = []
        if log_url:
            actions.append({
                'id': 'view-cleanup-log',
                'type': 'view_server_cleanup_log',
                'label': 'View Cleanup Log',
                'url': log_url,
            })
        return self._notification(
            key='server_cleanup_completed',
            title='Server Cleanup Completed with Errors' if error_count else 'Server Cleanup Completed',
            message=' · '.join(message_parts),
            type_='warning' if error_count else 'success',
            context={
                'run_id': payload.get('run_id') or '',
                'trigger': payload.get('trigger') or '',
                'removed_files': removed_files,
                'removed_dirs': int(payload.get('removed_dirs') or 0),
                'removed_records': removed_records,
                'bytes_freed': bytes_freed,
                'error_count': error_count,
            },
            actions=actions,
        )


    def _build_device_event(self, payload):
        client_id = str(payload.get('client_id') or '').strip()
        device = str(payload.get('hostname') or '').strip() or self._device_name(client_id)
        kind = str(payload.get('kind') or 'device.event').strip() or 'device.event'
        message = str(payload.get('message') or '').strip() or kind
        display_message = f'{device} · {message}' if device else message
        return self._notification(
            'device_event',
            'Device Event',
            display_message,
            'info',
            {
                'client_id': client_id,
                'hostname': payload.get('hostname') or '',
                'event_id': payload.get('event_id') or '',
                'kind': kind,
                'occurred_at': payload.get('occurred_at') or '',
                'source': payload.get('source') if isinstance(payload.get('source'), dict) else {},
                'data': payload.get('data') if isinstance(payload.get('data'), dict) else {},
            },
        )

    def _build_connection_online(self, payload):
        conn = payload.get('connection') if isinstance(payload.get('connection'), dict) else {}
        client_id = str(conn.get('client_id') or '').strip()
        hostname = str(conn.get('hostname') or '').strip()
        return self._notification(
            key='connection_online',
            title='Device Online',
            message=f'{hostname or client_id or "Unknown device"} is now available',
            type_='success',
            context={'client_id': client_id, 'hostname': hostname},
        )

    def _build_connection_offline(self, payload):
        conn = payload.get('connection') if isinstance(payload.get('connection'), dict) else {}
        client_id = str(payload.get('client_id') or conn.get('client_id') or '').strip()
        hostname = str(conn.get('hostname') or '').strip()
        return self._notification(
            key='connection_offline',
            title='Device Offline',
            message=f'{hostname or client_id or "Unknown device"} went offline',
            type_='warning',
            context={'client_id': client_id, 'hostname': hostname},
        )

    def _build_file_transfer_lifecycle(self, payload):
        lifecycle = str(payload.get('lifecycle') or '').strip().lower()
        if lifecycle not in {'started', 'stopped', 'error'}:
            return None
        state = str(payload.get('state') or '').strip().lower()
        filename = str(payload.get('filename') or 'File transfer').strip() or 'File transfer'
        client_id = str(payload.get('client_id') or '').strip()
        device_name = self._device_name(client_id)
        stage = str(payload.get('stage') or '').strip().lower()
        direction = str(payload.get('direction') or '').strip().lower()
        error_text = str(payload.get('error') or '').strip()
        if stage == 'uploading_to_server':
            route = 'Browser → Server'
        elif direction == 'server_to_client':
            route = f'Server → {device_name}'
        else:
            route = f'{device_name} → Server'
        context = {
            'transfer_id': payload.get('transfer_id') or '',
            'client_id': client_id,
            'filename': filename,
            'direction': direction,
            'state': state,
            'stage': stage,
        }
        actions = [{'id': 'open-transfers', 'type': 'open_transfers', 'label': 'Open Transfers', 'url': ''}]
        if lifecycle == 'started':
            return self._notification('file_transfer_started', 'File Transfer Started', f'{filename} · {route}', 'info', context, actions)
        if lifecycle == 'stopped':
            cancelled = state == 'cancelled'
            return self._notification(
                'file_transfer_stopped',
                'File Transfer Stopped' if cancelled else 'File Transfer Completed',
                f'{filename} · {"Cancelled" if cancelled else "Completed"} · {route}',
                'warning' if cancelled else 'success',
                context,
                actions,
            )
        context['error'] = error_text
        return self._notification('file_transfer_error', 'File Transfer Error', f'{filename} · {route}{f": {error_text}" if error_text else ""}', 'error', context, actions)

    def _build_background_job_lifecycle(self, payload):
        state = str(payload.get('state') or payload.get('status') or '').strip().lower()
        mapping = {
            'running': ('background_job_running', 'Background Job Started', 'success', 'started'),
            'stopped': ('background_job_stopped', 'Background Job Finished', 'success', 'finished'),
            'error': ('background_job_error', 'Background Job Error', 'error', 'ended with error'),
        }
        if state not in mapping:
            return None
        key, title, type_, state_text = mapping[state]
        client_id = str(payload.get('client_id') or '').strip()
        job_name = str(payload.get('display_name') or payload.get('job_key') or payload.get('job_name') or 'background job')
        return self._notification(
            key, title, f'{job_name} {state_text} on {self._device_name(client_id)}', type_,
            {
                'client_id': client_id,
                'job_id': payload.get('job_id') or '',
                'job_key': payload.get('job_key') or payload.get('job_name') or '',
                'display_name': payload.get('display_name') or '',
                'state': state,
            },
        )

    def _build_pty_lifecycle(self, payload):
        state = str(payload.get('state') or '').strip().lower()
        client_id = str(payload.get('client_id') or '').strip()
        device = self._device_name(client_id)
        context = {
            'client_id': client_id,
            'pty_session_id': payload.get('pty_session_id') or '',
            'state': state,
        }
        if state == 'opened':
            return self._notification('pty_opened', 'PTY Started', f'PTY session started on {device}', 'success', context)
        if state == 'closed':
            exit_code = payload.get('exit_code')
            context['exit_code'] = exit_code
            suffix = '' if exit_code is None else f', exit={exit_code}'
            return self._notification('pty_closed', 'PTY Stopped', f'PTY session stopped on {device}{suffix}', 'warning', context)
        if state == 'error':
            error_text = str(payload.get('error') or '').strip()
            context['error'] = error_text
            message = f'PTY session ended on {device}: {error_text}' if error_text else f'PTY session ended with an error on {device}'
            return self._notification('pty_error', 'PTY Error', message, 'error', context)
        return None

    def _build_screen_view_lifecycle(self, payload):
        state = str(payload.get('state') or '').strip().lower()
        client_id = str(payload.get('client_id') or '').strip()
        device = self._device_name(client_id)
        context = {
            'client_id': client_id,
            'screen_session_id': payload.get('screen_session_id') or '',
            'state': state,
        }
        if state == 'started':
            return self._notification('screen_view_started', 'Screen View Started', f'Screen view started on {device}', 'success', context)
        if state == 'closed':
            return self._notification('screen_view_closed', 'Screen View Stopped', f'Screen view stopped on {device}', 'warning', context)
        if state == 'error':
            error_text = str(payload.get('error') or '').strip()
            context['error'] = error_text
            message = f'Screen view ended on {device}: {error_text}' if error_text else f'Screen view ended with an error on {device}'
            return self._notification('screen_view_error', 'Screen View Error', message, 'error', context)
        return None

    def _build_artifact_created(self, payload):
        artifact_id = str(payload.get('artifact_id') or '').strip()
        if not artifact_id:
            return None
        file_name = str(payload.get('original_name') or payload.get('stored_name') or 'file').strip() or 'file'
        download_url = str(payload.get('download_url') or '').strip() or f'/api/artifacts/{artifact_id}/download'
        return self._notification(
            'artifact_created', 'File Ready', f'{file_name} has been saved', 'success',
            {
                'client_id': payload.get('client_id') or '',
                'artifact_id': artifact_id,
                'artifact_type': payload.get('artifact_type') or '',
                'category': payload.get('category') or '',
                'original_name': payload.get('original_name') or file_name,
            },
            [
                {'id': 'download', 'type': 'artifact_download', 'label': 'Download', 'url': download_url},
                {'id': 'preview', 'type': 'artifact_preview', 'label': 'Preview', 'url': ''},
                {'id': 'open-artifacts', 'type': 'open_artifacts', 'label': 'Open Artifacts', 'url': ''},
            ],
        )

    def _build_agent_build_lifecycle(self, payload):
        state = str(payload.get('state') or '').strip().lower()
        if state not in {'completed', 'error'}:
            return None
        file_name = str(payload.get('file_name') or '').strip()
        error_text = str(payload.get('error') or '').strip()
        context = {
            'state': state,
            'builder': payload.get('builder') or '',
            'target_os': payload.get('target_os') or '',
            'target_arch': payload.get('target_arch') or '',
            'source': payload.get('source') or '',
            'file_name': file_name,
            'error': error_text,
        }
        actions = []
        if state == 'completed' and payload.get('download_url'):
            actions.append({'id': 'download', 'type': 'agent_download', 'label': 'Download', 'url': payload.get('download_url')})
        actions.append({'id': 'open-agents', 'type': 'open_agents', 'label': 'Open Agents', 'url': ''})
        if state == 'completed':
            return self._notification('agent_build_completed', 'Agent Build Completed', f'Agent build completed successfully{f" · {file_name}" if file_name else ""}', 'success', context, actions)
        return self._notification('agent_build_error', 'Agent Build Error', f'Agent build failed{f": {error_text}" if error_text else ""}', 'error', context, actions)

    def _build_external_tool_lifecycle(self, payload):
        action = str(payload.get('action') or '').strip().lower()
        state = str(payload.get('state') or '').strip().lower()
        operation = str(payload.get('operation') or '').strip().lower()
        mapping = {
            ('daemon', 'started'): 'external_tool_daemon_started',
            ('daemon', 'stopped'): 'external_tool_daemon_stopped',
            ('daemon', 'error'): 'external_tool_daemon_error',
            ('install', 'completed'): 'external_tool_install_completed',
            ('install', 'failed'): 'external_tool_install_failed',
            ('uninstall', 'completed'): 'external_tool_uninstall_completed',
            ('uninstall', 'failed'): 'external_tool_uninstall_failed',
        }
        key = mapping.get((action, state))
        if not key:
            return None
        client_id = str(payload.get('client_id') or '').strip()
        device = self._device_name(client_id)
        service_name = str(payload.get('display_name') or payload.get('tool_id') or payload.get('package_id') or 'external tool').strip()
        instance_id = str(payload.get('instance_id') or '').strip()
        label = f'{service_name}/{instance_id}' if instance_id else service_name
        error_text = str(payload.get('error') or payload.get('message') or '').strip()
        context = {
            'client_id': client_id,
            'action': action,
            'state': state,
            'operation': operation,
            'tool_id': payload.get('tool_id') or '',
            'package_id': payload.get('package_id') or '',
            'module_id': payload.get('module_id') or '',
            'display_name': payload.get('display_name') or '',
            'instance_id': instance_id,
            'status': payload.get('status') or '',
            'pid': payload.get('pid'),
            'returncode': payload.get('returncode'),
            'duration_sec': payload.get('duration_sec'),
            'error': payload.get('error') or '',
            'log_excerpt': payload.get('log_excerpt') or '',
        }
        actions = [{'id': 'open-external-tools', 'type': 'open_external_tools', 'label': 'Open External Tools', 'url': ''}]
        if state in {'error', 'failed'}:
            actions.append({'id': 'view-log', 'type': 'view_external_tool_log', 'label': 'View Log', 'url': ''})

        if action == 'daemon' and state == 'started':
            return self._notification(key, 'External Tool Daemon Started', f'{device} · {label} daemon started successfully', 'success', context, actions)
        if action == 'daemon' and state == 'stopped':
            return self._notification(key, 'External Tool Daemon Stopped', f'{device} · {label} daemon stopped successfully', 'warning', context, actions)
        if action == 'daemon' and state == 'error':
            title = 'External Tool Daemon Stop Error' if operation == 'stop' else 'External Tool Daemon Start Error'
            return self._notification(key, title, f'{device} · {label} daemon {operation or "operation"} failed{f": {error_text}" if error_text else ""}', 'error', context, actions)
        if action == 'install' and state == 'completed':
            message = str(payload.get('message') or '').strip()
            return self._notification(key, 'External Tool Install Completed', f'{device} · {service_name} install completed{f": {message}" if message else " successfully"}', 'success', context, actions)
        if action == 'install' and state == 'failed':
            return self._notification(key, 'External Tool Install Failed', f'{device} · {service_name} install failed{f": {error_text}" if error_text else ""}', 'error', context, actions)
        if action == 'uninstall' and state == 'completed':
            message = str(payload.get('message') or '').strip()
            return self._notification(key, 'External Tool Uninstall Completed', f'{device} · {service_name} uninstall completed{f": {message}" if message else " successfully"}', 'success', context, actions)
        return self._notification(key, 'External Tool Uninstall Failed', f'{device} · {service_name} uninstall failed{f": {error_text}" if error_text else ""}', 'error', context, actions)

    def _device_name(self, client_id: str) -> str:
        normalized = str(client_id or '').strip()
        if not normalized:
            return 'Unknown device'
        try:
            session = self.server.get_target_connection_by_client_id(normalized)
            hostname = str(getattr(getattr(session, 'session_info', None), 'hostname', '') or '').strip()
            if hostname:
                return hostname
        except Exception:
            pass
        return normalized

    @staticmethod
    def _notification(key, title, message, type_='info', context=None, actions=None):
        return {
            'notification_key': key,
            'type': type_,
            'title': title,
            'message': message,
            'context': context or {},
            'actions': actions or [],
        }

    @staticmethod
    def _format_bytes(value: int) -> str:
        size = max(0, int(value or 0))
        if size < 1024:
            return f'{size} B'
        if size < 1024 * 1024:
            return f'{size / 1024:.1f} KB'
        if size < 1024 * 1024 * 1024:
            return f'{size / (1024 * 1024):.2f} MB'
        return f'{size / (1024 * 1024 * 1024):.2f} GB'
