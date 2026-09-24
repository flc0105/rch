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
        errors = []
        for meta in metas or []:
            tool_id = str(meta.get('tool_id') or '').strip()
            if not tool_id:
                continue
            tools.append({'tool_id': tool_id, 'package_id': meta.get('package_id') or '', 'module_id': meta.get('id') or '', 'display_name': meta.get('display_name') or tool_id})
        payload = {'action': 'list_all', 'tools': tools, 'errors': errors}
        command = f'external_tool_list_instances_all {self.payload_builder.encode_payload_arg(payload)}'
        result = self._run_client_lifecycle_command(client_id, command, tab_id=tab_id)
        if isinstance(result, dict):
            result.setdefault('side', 'client')
            result.setdefault('errors', errors)
            return result
        return result

    def _run_client_lifecycle_command(self, client_id: str, command: str, tab_id: str = '') -> dict:
        if self.remote_execution_service is None:
            return self.command_execution_api.submit_web_command(client_id, command, tab_id=tab_id)
        del tab_id
        return self.remote_execution_service.run_foreground_json_command(client_id, command, task_type='external_tool', source='web_external_tool')

    def resolve_client_launcher(self, client_id: str, tool_id: str, tab_id: str = '', platform_alias: str = '', arch: str = '') -> dict:
        meta = self.catalog_service.get_tool(tool_id)
        payload = self.payload_builder.build_client_launcher_payload(
            meta,
            platform_alias=platform_alias,
            arch=arch,
        )
        command = f'external_tool_resolve_launcher {self.payload_builder.encode_payload_arg(payload)}'
        return self._run_client_lifecycle_command(client_id, command, tab_id=tab_id)

    def start_client_instance(self, client_id: str, tool_id: str, params: dict | None = None, tab_id: str = '', instance_id: str = '', install_if_needed: bool = False, platform_alias: str = '', arch: str = '', launcher_override: dict | None = None) -> dict:
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
        command = f'external_tool_start {self.payload_builder.encode_payload_arg(payload)}'

        try:
            result = self._run_client_lifecycle_command(client_id, command, tab_id=tab_id)
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
        command = f'external_tool_preview {self.payload_builder.encode_payload_arg(payload)}'
        return self._run_client_lifecycle_command(client_id, command, tab_id=tab_id)

    def run_client_oneshot(self, client_id: str, tool_id: str, params: dict | None = None, tab_id: str = '', platform_alias: str = '', arch: str = '', launcher_override: dict | None = None) -> dict:
        meta = self.catalog_service.get_tool(tool_id)
        payload = self.payload_builder.build_client_oneshot_payload(
            meta,
            params=params,
            platform_alias=platform_alias,
            arch=arch,
            launcher_override=launcher_override,
        )
        command = f'external_tool_oneshot {self.payload_builder.encode_payload_arg(payload)}'
        return self._run_client_lifecycle_command(client_id, command, tab_id=tab_id)

    def install_client_tool(self, client_id: str, package_id: str, params: dict | None = None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = '') -> dict:
        del params, instance_id
        package = self.catalog_service.get_package(package_id)
        payload = self.payload_builder.build_client_install_payload(package, platform_alias=platform_alias, arch=arch)
        payload['action'] = 'install'
        command = f'external_tool_install {self.payload_builder.encode_payload_arg(payload)}'

        try:
            result = self._run_client_lifecycle_command(client_id, command, tab_id=tab_id)
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

        if isinstance(result, dict) and result.get('installed') is True:
            self._publish_lifecycle(
                client_id=client_id,
                action='install',
                state='completed',
                operation='install',
                package=package,
                result=result,
            )
        else:
            self._publish_lifecycle(
                client_id=client_id,
                action='install',
                state='failed',
                operation='install',
                package=package,
                result=result if isinstance(result, dict) else None,
                error=result.get('message') if isinstance(result, dict) else 'Install did not complete',
            )
        return result

    def client_install_status(self, client_id: str, package_id: str, params: dict | None = None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = '') -> dict:
        del params, instance_id
        package = self.catalog_service.get_package(package_id)
        payload = self.payload_builder.build_client_install_payload(package, platform_alias=platform_alias, arch=arch)
        payload['action'] = 'install_status'
        command = f'external_tool_install_status {self.payload_builder.encode_payload_arg(payload)}'
        return self._run_client_lifecycle_command(client_id, command, tab_id=tab_id)

    def uninstall_client_tool(self, client_id: str, package_id: str, params: dict | None = None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = '') -> dict:
        del params, instance_id
        package = self.catalog_service.get_package(package_id)
        payload = self.payload_builder.build_client_install_payload(package, platform_alias=platform_alias, arch=arch)
        payload['action'] = 'uninstall'
        command = f'external_tool_uninstall {self.payload_builder.encode_payload_arg(payload)}'

        try:
            result = self._run_client_lifecycle_command(client_id, command, tab_id=tab_id)
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

        if isinstance(result, dict) and result.get('installed') is False:
            self._publish_lifecycle(
                client_id=client_id,
                action='uninstall',
                state='completed',
                operation='uninstall',
                package=package,
                result=result,
            )
        else:
            self._publish_lifecycle(
                client_id=client_id,
                action='uninstall',
                state='failed',
                operation='uninstall',
                package=package,
                result=result if isinstance(result, dict) else None,
                error=result.get('message') if isinstance(result, dict) else 'Uninstall did not complete',
            )
        return result

    def client_install_statuses(self, client_id: str, packages: list[dict], tab_id: str = '', platform_alias: str = '', arch: str = '') -> dict:
        payload = {'action': 'install_statuses', 'tools': self.payload_builder.build_client_install_status_payloads(packages, platform_alias=platform_alias, arch=arch)}
        command = f'external_tool_install_statuses {self.payload_builder.encode_payload_arg(payload)}'
        return self._run_client_lifecycle_command(client_id, command, tab_id=tab_id)

    def clear_client_package_cache(self, client_id: str, package_id: str, params: dict | None = None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = '') -> dict:
        del params, instance_id
        package = self.catalog_service.get_package(package_id)
        payload = self.payload_builder.build_client_install_payload(package, platform_alias=platform_alias, arch=arch)
        payload['action'] = 'clear_cache'
        command = f'external_tool_clear_cache {self.payload_builder.encode_payload_arg(payload)}'
        return self._run_client_lifecycle_command(client_id, command, tab_id=tab_id)

    def stop_client_instance(self, client_id: str, tool_id: str, instance_id: str, params: dict | None = None, tab_id: str = '') -> dict:
        meta = self.catalog_service.get_tool(tool_id)
        payload = self.payload_builder.build_client_action_payload(meta, 'stop', instance_id=instance_id, params=params)
        resolved_instance_id = str(payload.get('instance_id') or instance_id or 'default').strip()
        command = f'external_tool_stop {self.payload_builder.encode_payload_arg(payload)}'

        try:
            result = self._run_client_lifecycle_command(client_id, command, tab_id=tab_id)
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
        payload = self.payload_builder.build_client_action_payload(meta, 'status', instance_id=instance_id)
        command = f'external_tool_status {self.payload_builder.encode_payload_arg(payload)}'
        return self._run_client_lifecycle_command(client_id, command, tab_id=tab_id)

    def list_client_instances(self, client_id: str, tool_id: str, tab_id: str = '') -> dict:
        meta = self.catalog_service.get_tool(tool_id)
        payload = {'action': 'list', 'tool_id': meta.get('tool_id') or '', 'package_id': meta.get('package_id') or '', 'module_id': meta.get('id') or '', 'display_name': meta.get('display_name') or meta.get('tool_id') or '', 'side': 'client'}
        command = f'external_tool_list_instances {self.payload_builder.encode_payload_arg(payload)}'
        return self._run_client_lifecycle_command(client_id, command, tab_id=tab_id)

    def read_client_logs(self, client_id: str, tool_id: str, instance_id: str, max_bytes: int | None = None, tab_id: str = '') -> dict:
        meta = self.catalog_service.get_tool(tool_id)
        payload = self.payload_builder.build_client_action_payload(meta, 'logs', instance_id=instance_id, max_bytes=max_bytes)
        command = f'external_tool_logs {self.payload_builder.encode_payload_arg(payload)}'
        return self._run_client_lifecycle_command(client_id, command, tab_id=tab_id)

    def remove_client_instance(self, client_id: str, tool_id: str, instance_id: str, tab_id: str = '') -> dict:
        meta = self.catalog_service.get_tool(tool_id)
        payload = self.payload_builder.build_client_action_payload(meta, 'remove', instance_id=instance_id)
        command = f'external_tool_remove {self.payload_builder.encode_payload_arg(payload)}'
        return self._run_client_lifecycle_command(client_id, command, tab_id=tab_id)

    def clear_client_logs(self, client_id: str, tool_id: str, instance_id: str, tab_id: str = '') -> dict:
        meta = self.catalog_service.get_tool(tool_id)
        payload = self.payload_builder.build_client_action_payload(meta, 'clear_logs', instance_id=instance_id)
        command = f'external_tool_clear_logs {self.payload_builder.encode_payload_arg(payload)}'
        return self._run_client_lifecycle_command(client_id, command, tab_id=tab_id)
