from core.external_tools.payload import primary_binary_name
from server.application.external_tools.external_tool_runtime_component import ExternalToolRuntimeComponent


class ExternalToolInstallSupport(ExternalToolRuntimeComponent):
    """Client install payload helpers."""

    def _primary_binary_name(self, package: dict, module: dict | None = None) -> str:
        return primary_binary_name(package, module)

    def _default_package_skip_template(self, package: dict, context: dict) -> str:
        del package, context
        # Package-first install state should be tied to the package extraction
        # directory, not to one runnable executable. Multi-binary packages such as
        # frp can expose frps/frpc from the same installation, and using the first
        # binary as the package marker makes status fragile. Module start still
        # validates the concrete executable through runtime.argv.
        return '{{install_dir}}'

    def _client_skip_path(self, package: dict, context: dict, module: dict | None = None) -> str:
        del module
        install = package.get('install') if isinstance(package.get('install'), dict) else {}
        package_file = self._package_file(package, context.get('package_key') or '')
        skip_template = str(package_file.get('skip_if_exists') or install.get('skip_if_exists') or '').strip()
        if not skip_template:
            skip_template = self._default_package_skip_template(package, context)
        return self._render_value(skip_template, context)
