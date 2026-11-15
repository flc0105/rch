from core.protocol.control import ControlDomain, ExternalToolAction as A
from core.external_tools.payload import client_control_request

from server.application.external_tools.external_tool_runtime_component import ExternalToolRuntimeComponent


class ExternalToolClientLifecycleRuntime(ExternalToolRuntimeComponent):
    """Client-targeted external tool lifecycle command dispatch."""

    def __init__(self, core, payload_builder, event_bus=None):
        super().__init__(core)
        self.payload_builder = payload_builder
        self.event_bus = event_bus

    @staticmethod
    def _trim_text(value, limit: int = 4000) -> str:
        text = str(value or '').strip()
        if len(text) <= limit:
            return text
        return text[:limit] + '\n...[truncated]'

    def _publish_lifecycle(
        self,
        *,
        client_id: str,
        action: str,
        state: str,
        operation: str = '',
        meta: dict | None = None,
        package: dict | None = None,
        instance_id: str = '',
        result: dict | None = None,
        error: str = '',
    ):
        if self.event_bus is None:
            return

        source = meta if isinstance(meta, dict) else package if isinstance(package, dict) else {}
        package_data = package if isinstance(package, dict) else {}
        result_data = result if isinstance(result, dict) else {}
        payload = {
            'client_id': str(client_id or '').strip(),
            'action': str(action or '').strip().lower(),
            'state': str(state or '').strip().lower(),
            'operation': str(operation or '').strip().lower(),
            'execution': str(source.get('execution') or '').strip().lower(),
            'tool_id': str(result_data.get('tool_id') or source.get('tool_id') or source.get('id') or '').strip(),
            'package_id': str(result_data.get('package_id') or source.get('package_id') or package_data.get('id') or '').strip(),
            'module_id': str(result_data.get('module_id') or source.get('module_id') or source.get('id') or '').strip(),
            'display_name': str(result_data.get('display_name') or source.get('display_name') or source.get('name') or source.get('id') or '').strip(),
            'instance_id': str(result_data.get('instance_id') or instance_id or '').strip(),
            'status': str(result_data.get('status') or '').strip(),
            'pid': result_data.get('pid'),
            'returncode': result_data.get('returncode'),
            'duration_sec': result_data.get('duration_sec'),
            'message': self._trim_text(result_data.get('message')),
            'error': self._trim_text(error),
        }

        log_parts = []
        if payload['state'] in {'error', 'failed'}:
            stderr = self._trim_text(result_data.get('stderr'))
            stdout = self._trim_text(result_data.get('stdout'))
            if stderr:
                log_parts.append(stderr)
            if stdout:
                log_parts.append(stdout)
        payload['log_excerpt'] = self._trim_text('\n'.join(log_parts), 8000)

        self.event_bus.publish('external_tool_lifecycle', payload)

    def list_all_client_instances(self, client_id: str, metas: list[dict], tab_id: str = '') -> dict:
        tools = []
        for meta in metas or []:
            tool_id = str(meta.get('tool_id') or '').strip()
            if not tool_id:
                continue
            tools.append({'tool_id': tool_id, 'package_id': meta.get('package_id') or '', 'module_id': meta.get('id') or '', 'display_name': meta.get('display_name') or tool_id})
        payload = {'tools': tools}
        action = A.LIST_INSTANCES
        result = self._run_client_control(client_id, action, payload, tab_id=tab_id)
        if isinstance(result, dict):
            result.setdefault('side', 'client')
            result.setdefault('errors', [])
            return result
        return result

    def _run_client_control(self, client_id: str, action, payload: dict, *,
                            tab_id: str = '', history_entry_id: str = '',
                            message_only: bool = False, return_failed_data: bool = False,
                            include_message: bool = False) -> dict:
        # Metadata is resolved on the Server; the action belongs to the Control
        # envelope, not another "action" field inside its business payload.
        del tab_id
        if self.remote_execution_service is None:
            raise RuntimeError('External Tool Control transport is not available')
        status, result = self.remote_execution_service.run_foreground_control(
            client_id, ControlDomain.EXTERNAL_TOOL, action,
            client_control_request(action, payload),
            task_type='external_tool', source='web_external_tool',
            history_entry_id=history_entry_id,
        )
        if not isinstance(result, dict) or result.get('event_type') != 'completed':
            raise RuntimeError(str(result) or 'External Tool Control returned no completion')
        data = result.get('data')
        if status != 1:
            if return_failed_data and isinstance(data, dict) and data.get('success') is False:
                return {'message': str(result.get('message') or ''), **data} if include_message else data
            raise RuntimeError(str(result.get('message') or f'External Tool {action} failed'))
        if message_only:
            return {'message': str(result.get('message') or '')}
        if not isinstance(data, dict):
            raise RuntimeError(f'Invalid External Tool {action} data')
        return {'message': str(result.get('message') or ''), **data} if include_message else data

    @staticmethod
    def _single_item(result: dict, key: str) -> dict:
        items = result.get('items') if isinstance(result, dict) else None
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            raise RuntimeError(f'Invalid External Tool {key} result')
        if items[0].get('error'):
            raise RuntimeError(str(items[0]['error']))
        return items[0]

    def resolve_client_launcher(self, client_id: str, tool_id: str, tab_id: str = '', platform_alias: str = '', arch: str = '') -> dict:
        meta = self.catalog_service.get_tool(tool_id)
        payload = self.payload_builder.build_client_launcher_payload(
            meta,
            platform_alias=platform_alias,
            arch=arch,
        )
        action = A.RESOLVE_LAUNCHER
        return self._run_client_control(client_id, action, payload, tab_id=tab_id)

    def start_client_instance(self, client_id: str, tool_id: str, params: dict | None = None, tab_id: str = '', instance_id: str = '', install_if_needed: bool = False, platform_alias: str = '', arch: str = '', launcher_override: dict | None = None, history_entry_id: str = '') -> dict:
        del install_if_needed
        meta = self.catalog_service.get_tool(tool_id)
        payload = self.payload_builder.build_client_start_payload(
            meta,
            params=params,
            instance_id=instance_id,
            platform_alias=platform_alias,
            arch=arch,
            launcher_override=launcher_override,
        )
        resolved_instance_id = str(payload.get('instance_id') or instance_id or 'default').strip()
        action = A.START_INSTANCE

        try:
            result = self._run_client_control(client_id, action, payload, tab_id=tab_id, history_entry_id=history_entry_id)
        except Exception as exc:
            self._publish_lifecycle(
                client_id=client_id,
                action='daemon',
                state='error',
                operation='start',
                meta=meta,
                instance_id=resolved_instance_id,
                error=str(exc),
            )
            raise

        message = str(result.get('message') or '').strip().lower() if isinstance(result, dict) else ''
        if isinstance(result, dict) and result.get('running') is True and 'already running' not in message:
            self._publish_lifecycle(
                client_id=client_id,
                action='daemon',
                state='started',
                operation='start',
                meta=meta,
                instance_id=resolved_instance_id,
                result=result,
            )
        elif isinstance(result, dict) and result.get('running') is not True:
            self._publish_lifecycle(
                client_id=client_id,
                action='daemon',
                state='error',
                operation='start',
                meta=meta,
                instance_id=resolved_instance_id,
                result=result,
                error=result.get('message') or 'Daemon did not enter running state',
            )

        return result

    def preview_client_instance_command(self, client_id: str, tool_id: str, params: dict | None = None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = '', launcher_override: dict | None = None) -> dict:
        meta = self.catalog_service.get_tool(tool_id)
        if str(meta.get('execution') or '').strip().lower() != 'daemon':
            raise ValueError('command preview is only available for daemon instances')
        payload = self.payload_builder.build_client_start_payload(
            meta,
            params=params,
            instance_id=instance_id,
            platform_alias=platform_alias,
            arch=arch,
            launcher_override=launcher_override,
        )
        action = A.PREVIEW_INSTANCE
        return self._run_client_control(client_id, action, payload, tab_id=tab_id)

    def run_client_oneshot(self, client_id: str, tool_id: str, params: dict | None = None, tab_id: str = '', platform_alias: str = '', arch: str = '', launcher_override: dict | None = None, history_entry_id: str = '') -> dict:
        meta = self.catalog_service.get_tool(tool_id)
        payload = self.payload_builder.build_client_oneshot_payload(
            meta,
            params=params,
            platform_alias=platform_alias,
            arch=arch,
            launcher_override=launcher_override,
        )
        action = A.RUN_ONESHOT
        return self._run_client_control(client_id, action, payload, tab_id=tab_id,
                                        history_entry_id=history_entry_id,
                                        return_failed_data=True, include_message=True)

    def install_client_tool(self, client_id: str, package_id: str, params: dict | None = None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = '', history_entry_id: str = '') -> dict:
        del params, instance_id
        package = self.catalog_service.get_package(package_id)
        payload = self.payload_builder.build_client_install_payload(package, platform_alias=platform_alias, arch=arch)
        action = A.INSTALL_PACKAGE

        try:
            result = self._run_client_control(client_id, action, payload, tab_id=tab_id,
                                              history_entry_id=history_entry_id, message_only=True)
        except Exception as exc:
            self._publish_lifecycle(
                client_id=client_id,
                action='install',
                state='failed',
                operation='install',
                package=package,
                error=str(exc),
            )
            raise

        self._publish_lifecycle(
            client_id=client_id,
            action='install',
            state='completed',
            operation='install',
            package=package,
            result=result,
        )
        return result

    def client_install_status(self, client_id: str, package_id: str, params: dict | None = None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = '') -> dict:
        del params, instance_id
        package = self.catalog_service.get_package(package_id)
        payload = self.payload_builder.build_client_install_payload(package, platform_alias=platform_alias, arch=arch)
        return self._single_item(self._run_client_control(
            client_id, A.GET_INSTALL_STATUSES, {'tools': [payload]}, tab_id=tab_id,
        ), 'get_install_statuses')

    def uninstall_client_tool(self, client_id: str, package_id: str, params: dict | None = None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = '', history_entry_id: str = '') -> dict:
        del params, instance_id
        package = self.catalog_service.get_package(package_id)
        payload = self.payload_builder.build_client_install_payload(package, platform_alias=platform_alias, arch=arch)
        action = A.UNINSTALL_PACKAGE

        try:
            result = self._run_client_control(client_id, action, payload, tab_id=tab_id,
                                              history_entry_id=history_entry_id, message_only=True)
        except Exception as exc:
            self._publish_lifecycle(
                client_id=client_id,
                action='uninstall',
                state='failed',
                operation='uninstall',
                package=package,
                error=str(exc),
            )
            raise

        self._publish_lifecycle(
            client_id=client_id,
            action='uninstall',
            state='completed',
            operation='uninstall',
            package=package,
            result=result,
        )
        return result

    def client_install_statuses(self, client_id: str, packages: list[dict], tab_id: str = '', platform_alias: str = '', arch: str = '') -> dict:
        payload = {'tools': self.payload_builder.build_client_install_status_payloads(packages, platform_alias=platform_alias, arch=arch)}
        action = A.GET_INSTALL_STATUSES
        return self._run_client_control(client_id, action, payload, tab_id=tab_id)

    def clear_client_package_cache(self, client_id: str, package_id: str, params: dict | None = None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = '', history_entry_id: str = '') -> dict:
        del params, instance_id
        package = self.catalog_service.get_package(package_id)
        payload = self.payload_builder.build_client_install_payload(package, platform_alias=platform_alias, arch=arch)
        action = A.CLEAR_PACKAGE_CACHE
        return self._run_client_control(client_id, action, payload, tab_id=tab_id,
                                        history_entry_id=history_entry_id, message_only=True)

    def stop_client_instance(self, client_id: str, tool_id: str, instance_id: str, params: dict | None = None, tab_id: str = '', history_entry_id: str = '') -> dict:
        meta = self.catalog_service.get_tool(tool_id)
        payload = self.payload_builder.build_client_action_payload(meta, 'stop', instance_id=instance_id, params=params)
        resolved_instance_id = str(payload.get('instance_id') or instance_id or 'default').strip()
        action = A.STOP_INSTANCE

        try:
            result = self._run_client_control(client_id, action, payload, tab_id=tab_id, history_entry_id=history_entry_id)
        except Exception as exc:
            self._publish_lifecycle(
                client_id=client_id,
                action='daemon',
                state='error',
                operation='stop',
                meta=meta,
                instance_id=resolved_instance_id,
                error=str(exc),
            )
            raise

        stop_result = result.get('stop_result') if isinstance(result, dict) and isinstance(result.get('stop_result'), dict) else {}
        if isinstance(result, dict) and result.get('running') is False and not stop_result.get('already_stopped'):
            self._publish_lifecycle(
                client_id=client_id,
                action='daemon',
                state='stopped',
                operation='stop',
                meta=meta,
                instance_id=resolved_instance_id,
                result=result,
            )
        elif isinstance(result, dict) and result.get('running') is True:
            self._publish_lifecycle(
                client_id=client_id,
                action='daemon',
                state='error',
                operation='stop',
                meta=meta,
                instance_id=resolved_instance_id,
                result=result,
                error='Daemon stop completed but the process is still running',
            )

        return result

    def status_client_instance(self, client_id: str, tool_id: str, instance_id: str, tab_id: str = '') -> dict:
        meta = self.catalog_service.get_tool(tool_id)
        payload = {'tools': [{'tool_id': meta['tool_id'], 'package_id': meta['package_id'],
                              'module_id': meta['id'], 'instance_ids': [instance_id]}]}
        return self._single_item(self._run_client_control(
            client_id, A.LIST_INSTANCES, payload, tab_id=tab_id,
        ), 'list_instances')

    def list_client_instances(self, client_id: str, tool_id: str, tab_id: str = '') -> dict:
        meta = self.catalog_service.get_tool(tool_id)
        payload = {'tools': [{'tool_id': meta['tool_id'], 'package_id': meta['package_id'],
                              'module_id': meta['id']}]}
        result = self._run_client_control(client_id, A.LIST_INSTANCES, payload, tab_id=tab_id)
        return {'tool_id': meta['tool_id'], 'package_id': meta['package_id'],
                'module_id': meta['id'], 'side': 'client', 'items': result['items']}

    def remove_client_instance(self, client_id: str, tool_id: str, instance_id: str, tab_id: str = '', history_entry_id: str = '') -> dict:
        meta = self.catalog_service.get_tool(tool_id)
        payload = self.payload_builder.build_client_action_payload(meta, 'remove', instance_id=instance_id)
        action = A.REMOVE_INSTANCE
        return self._run_client_control(client_id, action, payload, tab_id=tab_id, history_entry_id=history_entry_id)

    def clear_client_logs(self, client_id: str, tool_id: str, instance_id: str, tab_id: str = '', history_entry_id: str = '') -> dict:
        meta = self.catalog_service.get_tool(tool_id)
        payload = self.payload_builder.build_client_action_payload(meta, 'clear_logs', instance_id=instance_id)
        action = A.CLEAR_INSTANCE_LOGS
        return self._run_client_control(client_id, action, payload, tab_id=tab_id, history_entry_id=history_entry_id)
