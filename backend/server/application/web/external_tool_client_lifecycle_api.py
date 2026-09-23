class WebExternalToolClientLifecycleApi:
    def __init__(self, catalog_service, runtime_service):
        self.catalog_service = catalog_service
        self.runtime_service = runtime_service

    def install_client_tool(self, client_id: str, package_id: str, params=None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = ''):
        return self.runtime_service.client_lifecycle_runtime.install_client_tool(client_id, package_id, params=params, tab_id=tab_id, instance_id=instance_id, platform_alias=platform_alias, arch=arch)

    def client_install_status(self, client_id: str, package_id: str, params=None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = ''):
        return self.runtime_service.client_lifecycle_runtime.client_install_status(client_id, package_id, params=params, tab_id=tab_id, instance_id=instance_id, platform_alias=platform_alias, arch=arch)

    def client_install_statuses(self, client_id: str, tab_id: str = '', platform_alias: str = '', arch: str = ''):
        packages = [item for item in (self.catalog_service.get_catalog().get('items') or []) if not item.get('error')]
        return self.runtime_service.client_lifecycle_runtime.client_install_statuses(client_id, packages, tab_id=tab_id, platform_alias=platform_alias, arch=arch)

    def uninstall_client_tool(self, client_id: str, package_id: str, params=None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = ''):
        return self.runtime_service.client_lifecycle_runtime.uninstall_client_tool(client_id, package_id, params=params, tab_id=tab_id, instance_id=instance_id, platform_alias=platform_alias, arch=arch)

    def clear_client_package_cache(self, client_id: str, package_id: str, params=None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = ''):
        return self.runtime_service.client_lifecycle_runtime.clear_client_package_cache(client_id, package_id, params=params, tab_id=tab_id, instance_id=instance_id, platform_alias=platform_alias, arch=arch)

    def resolve_client_launcher(self, client_id: str, tool_id: str, tab_id: str = '', platform_alias: str = '', arch: str = ''):
        return self.runtime_service.client_lifecycle_runtime.resolve_client_launcher(client_id, tool_id, tab_id=tab_id, platform_alias=platform_alias, arch=arch)

    def start_client_instance(self, client_id: str, tool_id: str, params=None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = '', launcher_override=None):
        return self.runtime_service.client_lifecycle_runtime.start_client_instance(client_id, tool_id, params=params, tab_id=tab_id, instance_id=instance_id, install_if_needed=False, platform_alias=platform_alias, arch=arch, launcher_override=launcher_override)

    def preview_client_instance_command(self, client_id: str, tool_id: str, params=None, tab_id: str = '', instance_id: str = '', platform_alias: str = '', arch: str = '', launcher_override=None):
        return self.runtime_service.client_lifecycle_runtime.preview_client_instance_command(client_id, tool_id, params=params, tab_id=tab_id, instance_id=instance_id, platform_alias=platform_alias, arch=arch, launcher_override=launcher_override)

    def run_client_oneshot(self, client_id: str, tool_id: str, params=None, tab_id: str = '', platform_alias: str = '', arch: str = ''):
        return self.runtime_service.client_lifecycle_runtime.run_client_oneshot(client_id, tool_id, params=params, tab_id=tab_id, platform_alias=platform_alias, arch=arch)

    def stop_client_instance(self, client_id: str, tool_id: str, instance_id: str, params=None, tab_id: str = ''):
        return self.runtime_service.client_lifecycle_runtime.stop_client_instance(client_id, tool_id, instance_id=instance_id, params=params, tab_id=tab_id)

    def status_client_instance(self, client_id: str, tool_id: str, instance_id: str, tab_id: str = ''):
        return self.runtime_service.client_lifecycle_runtime.status_client_instance(client_id, tool_id, instance_id=instance_id, tab_id=tab_id)

    def list_client_instances(self, client_id: str, tool_id: str, tab_id: str = ''):
        return self.runtime_service.client_lifecycle_runtime.list_client_instances(client_id, tool_id, tab_id=tab_id)

    def list_all_client_instances(self, client_id: str, tab_id: str = ''):
        modules = [item for item in (self.catalog_service.get_catalog().get('modules') or []) if not item.get('error')]
        return self.runtime_service.client_lifecycle_runtime.list_all_client_instances(client_id, modules, tab_id=tab_id)

    def read_client_logs(self, client_id: str, tool_id: str, instance_id: str, max_bytes=None, tab_id: str = ''):
        return self.runtime_service.client_lifecycle_runtime.read_client_logs(client_id, tool_id, instance_id=instance_id, max_bytes=max_bytes, tab_id=tab_id)

    def remove_client_instance(self, client_id: str, tool_id: str, instance_id: str, tab_id: str = ''):
        return self.runtime_service.client_lifecycle_runtime.remove_client_instance(client_id, tool_id, instance_id=instance_id, tab_id=tab_id)

    def clear_client_logs(self, client_id: str, tool_id: str, instance_id: str, tab_id: str = ''):
        return self.runtime_service.client_lifecycle_runtime.clear_client_logs(client_id, tool_id, instance_id=instance_id, tab_id=tab_id)
