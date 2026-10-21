class WebExternalToolClientLifecycleApi:
    def __init__(self, catalog_service, runtime_service):
        self.catalog_service = catalog_service
        self.runtime_service = runtime_service

    def _record_action(self, client_id, action, identity, command_name, execute, *, origin):
        runner = self.runtime_service.core.remote_execution_service
        orchestrator = getattr(runner, 'history_orchestrator', None) if runner is not None else None
        conn = runner.get_connection(client_id) if orchestrator else None
        entry_id = (orchestrator.begin_external_tool_execution(conn, action, identity, command_name, origin=origin)
                    if orchestrator else '')
        try:
            result = execute(entry_id)
        except Exception:
            if entry_id:
                # After actual dispatch an error is recorded; before dispatch there is no row.
                orchestrator.append_output(conn, entry_id, 0, 'External tool operation failed')
                orchestrator.finalize_execution(conn, entry_id, False)
            raise
        if entry_id:
            status = self._result_status(action, result)
            noun = identity.get('package_id') or identity.get('tool_id') or 'External tool'
            instance = identity.get('instance_id') or (result.get('instance_id') if isinstance(result, dict) else '')
            summary = f'{action.replace("_", " ").capitalize()}: {noun}'
            if instance:
                summary += f' ({instance})'
            summary += ' completed' if status == 'success' else ' failed'
            orchestrator.append_output(conn, entry_id, int(status == 'success'), summary)
            orchestrator.finalize_execution(conn, entry_id, status == 'success', status=status)
        return result

    @staticmethod
    def _result_status(action, result):
        if not isinstance(result, dict):
            return 'error'
        if action == 'install_package':
            ok = result.get('installed') is True
        elif action == 'uninstall_package':
            ok = result.get('installed') is False
        elif action == 'start_instance':
            ok = result.get('running') is True
        elif action == 'stop_instance':
            ok = result.get('running') is False
        elif action == 'run_oneshot':
            if result.get('timed_out') is True:
                return 'timed_out'
            ok = result.get('success') is True and result.get('returncode') == 0
        elif action == 'clear_package_cache':
            ok = isinstance(result.get('cache'), dict) and isinstance(result.get('cache_removed'), bool)
        elif action == 'remove_instance':
            ok = result.get('removed') is True
        elif action == 'clear_instance_logs':
            ok = result.get('cleared') is True
        else:
            ok = False
        return 'success' if ok else 'error'

    def install_client_tool(self, client_id: str, package_id: str, params=None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = '', origin: str = 'web_api'):
        return self._record_action(client_id, 'install_package', {'package_id': package_id}, 'external_tool_install',
            lambda history_entry_id: self.runtime_service.client_lifecycle_runtime.install_client_tool(client_id, package_id, params=params, tab_id=tab_id, instance_id=instance_id, platform_alias=platform_alias, arch=arch, history_entry_id=history_entry_id), origin=origin)

    def client_install_status(self, client_id: str, package_id: str, params=None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = ''):
        return self.runtime_service.client_lifecycle_runtime.client_install_status(client_id, package_id, params=params, tab_id=tab_id, instance_id=instance_id, platform_alias=platform_alias, arch=arch)

    def client_install_statuses(self, client_id: str, tab_id: str = '', platform_alias: str = '', arch: str = ''):
        packages = [item for item in (self.catalog_service.get_catalog().get('items') or []) if not item.get('error')]
        return self.runtime_service.client_lifecycle_runtime.client_install_statuses(client_id, packages, tab_id=tab_id, platform_alias=platform_alias, arch=arch)

    def uninstall_client_tool(self, client_id: str, package_id: str, params=None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = '', origin: str = 'web_api'):
        return self._record_action(client_id, 'uninstall_package', {'package_id': package_id}, 'external_tool_uninstall',
            lambda history_entry_id: self.runtime_service.client_lifecycle_runtime.uninstall_client_tool(client_id, package_id, params=params, tab_id=tab_id, instance_id=instance_id, platform_alias=platform_alias, arch=arch, history_entry_id=history_entry_id), origin=origin)

    def clear_client_package_cache(self, client_id: str, package_id: str, params=None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = '', origin: str = 'web_api'):
        return self._record_action(client_id, 'clear_package_cache', {'package_id': package_id}, 'external_tool_clear_cache',
            lambda history_entry_id: self.runtime_service.client_lifecycle_runtime.clear_client_package_cache(client_id, package_id, params=params, tab_id=tab_id, instance_id=instance_id, platform_alias=platform_alias, arch=arch, history_entry_id=history_entry_id), origin=origin)

    def resolve_client_launcher(self, client_id: str, tool_id: str, tab_id: str = '', platform_alias: str = '', arch: str = ''):
        return self.runtime_service.client_lifecycle_runtime.resolve_client_launcher(client_id, tool_id, tab_id=tab_id, platform_alias=platform_alias, arch=arch)

    def start_client_instance(self, client_id: str, tool_id: str, params=None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = '', launcher_override=None, origin: str = 'web_api'):
        return self._record_action(client_id, 'start_instance', {'tool_id': tool_id, **({'instance_id': instance_id} if instance_id else {})}, 'external_tool_start',
            lambda history_entry_id: self.runtime_service.client_lifecycle_runtime.start_client_instance(client_id, tool_id, params=params, tab_id=tab_id, instance_id=instance_id, install_if_needed=False, platform_alias=platform_alias, arch=arch, launcher_override=launcher_override, history_entry_id=history_entry_id), origin=origin)

    def preview_client_instance_command(self, client_id: str, tool_id: str, params=None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = '', launcher_override=None):
        return self.runtime_service.client_lifecycle_runtime.preview_client_instance_command(client_id, tool_id, params=params, tab_id=tab_id, instance_id=instance_id, platform_alias=platform_alias, arch=arch, launcher_override=launcher_override)

    def run_client_oneshot(self, client_id: str, tool_id: str, params=None, tab_id: str = '', platform_alias: str = '', arch: str = '', launcher_override=None, origin: str = 'web_api'):
        return self._record_action(
            client_id, 'run_oneshot', {'tool_id': tool_id}, 'external_tool_oneshot',
            lambda history_entry_id: self.runtime_service.client_lifecycle_runtime.run_client_oneshot(
                client_id, tool_id, params=params, tab_id=tab_id, platform_alias=platform_alias,
                arch=arch, launcher_override=launcher_override, history_entry_id=history_entry_id,
            ), origin=origin,
        )

    def stop_client_instance(self, client_id: str, tool_id: str, instance_id: str, params=None, tab_id: str = '', origin: str = 'web_api'):
        return self._record_action(client_id, 'stop_instance', {'tool_id': tool_id, 'instance_id': instance_id}, 'external_tool_stop',
            lambda history_entry_id: self.runtime_service.client_lifecycle_runtime.stop_client_instance(client_id, tool_id, instance_id=instance_id, params=params, tab_id=tab_id, history_entry_id=history_entry_id), origin=origin)

    def status_client_instance(self, client_id: str, tool_id: str, instance_id: str, tab_id: str = ''):
        return self.runtime_service.client_lifecycle_runtime.status_client_instance(client_id, tool_id, instance_id=instance_id, tab_id=tab_id)

    def list_client_instances(self, client_id: str, tool_id: str, tab_id: str = ''):
        return self.runtime_service.client_lifecycle_runtime.list_client_instances(client_id, tool_id, tab_id=tab_id)

    def list_all_client_instances(self, client_id: str, tab_id: str = ''):
        modules = [item for item in (self.catalog_service.get_catalog().get('modules') or []) if not item.get('error')]
        return self.runtime_service.client_lifecycle_runtime.list_all_client_instances(client_id, modules, tab_id=tab_id)

    def remove_client_instance(self, client_id: str, tool_id: str, instance_id: str, tab_id: str = '', origin: str = 'web_api'):
        return self._record_action(client_id, 'remove_instance', {'tool_id': tool_id, 'instance_id': instance_id}, 'external_tool_remove',
            lambda history_entry_id: self.runtime_service.client_lifecycle_runtime.remove_client_instance(client_id, tool_id, instance_id=instance_id, tab_id=tab_id, history_entry_id=history_entry_id), origin=origin)

    def clear_client_logs(self, client_id: str, tool_id: str, instance_id: str, tab_id: str = '', origin: str = 'web_api'):
        return self._record_action(client_id, 'clear_instance_logs', {'tool_id': tool_id, 'instance_id': instance_id}, 'external_tool_clear_logs',
            lambda history_entry_id: self.runtime_service.client_lifecycle_runtime.clear_client_logs(client_id, tool_id, instance_id=instance_id, tab_id=tab_id, history_entry_id=history_entry_id), origin=origin)
