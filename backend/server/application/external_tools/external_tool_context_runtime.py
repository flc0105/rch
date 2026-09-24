import os
import re
from typing import Any

from core.external_tools.paths import (
    EXTERNAL_TOOLS_INSTALL_ROOT,
    EXTERNAL_TOOLS_RUNTIME_ROOT,
    external_tool_instance_runtime_parts,
)
from server.application.external_tools.external_tool_runtime_component import ExternalToolRuntimeComponent

class ExternalToolContextRuntime(ExternalToolRuntimeComponent):
    """Package/module context builders for client targets."""

    def _derive_instance_id(self, meta: dict, params: dict | None, explicit: str = '') -> str:
        params = params if isinstance(params, dict) else {}
        raw = explicit or params.get('instance_id') or params.get('instance_name')
        if not raw:
            proxy_name = str(params.get('proxy_name') or '').strip()
            remote_port = str(params.get('remote_port') or '').strip()
            bind_port = str(params.get('bind_port') or '').strip()
            if proxy_name and remote_port:
                raw = f'{proxy_name}-{remote_port}'
            elif bind_port:
                raw = f'{meta.get("name") or meta.get("id")}-{bind_port}'
            else:
                raw = 'default'
        return self._sanitize_instance_id(raw)
    def _package_base_context(
        self,
        package: dict,
        *,
        install_root: str,
        runtime_root: str,
        platform_alias: str,
        arch: str,
    ) -> dict:
        version = str(package.get('version') or 'default').strip() or 'default'
        package_id = str(package.get('id') or '').strip()
        platform_value, arch_value = self._require_target(platform_alias, arch, f'package {package_id or package.get("id") or "unknown"}')
        package_key = self._select_package_key(package, platform_value, arch_value)
        package_file = self._package_file(package, package_key)
        context = {
            'id': package_id,
            'package_id': package_id,
            'name': str(package.get('name') or package_id),
            'display_name': str(package.get('display_name') or package_id),
            'version': version,
            'platform': platform_value,
            'arch': arch_value,
            'package_key': package_key,
            'package_root': package_file.get('root') or '',
            'external_tools_root': install_root,
            'external_tools_runtime': runtime_root,
            'runtime_dir': runtime_root,
        }
        install_template = str((package.get('install') or {}).get('install_dir') or '{{external_tools_root}}/{{package_id}}/{{version}}/{{package_key}}')
        install_dir = self._render_value(install_template, context)
        context['install_dir'] = install_dir
        rel_execs, abs_bins = self._resolved_exec_context(package, package_key, install_dir)
        context['exec'] = rel_execs
        context['bin'] = abs_bins
        for name, rel_path in rel_execs.items():
            safe = re.sub(r'[^A-Za-z0-9_]+', '_', name).strip('_')
            context[f'exec_{safe}'] = rel_path
            context[f'bin_{safe}'] = abs_bins.get(name) or ''
        return context
    def _module_base_context(
        self,
        meta: dict,
        params: dict,
        *,
        install_root: str,
        runtime_root: str,
        instance_id: str = '',
        side: str = '',
        platform_alias: str = '',
        arch: str = '',
    ) -> dict:
        package = meta.get('package_meta') if isinstance(meta.get('package_meta'), dict) else self.catalog_service.get_package(meta.get('package_id') or '')
        context = self._package_base_context(
            package,
            install_root=install_root,
            runtime_root=runtime_root,
            platform_alias=platform_alias,
            arch=arch,
        )
        params = params if isinstance(params, dict) else {}
        resolved_instance_id = self._derive_instance_id(meta, params, explicit=instance_id)
        package_id = str(meta.get('package_id') or package.get('id') or '').strip()
        module_id = str(meta.get('id') or meta.get('module_id') or '').strip()
        tool_id = str(meta.get('tool_id') or f'{package_id}.{module_id}').strip()
        tool_runtime_dir = os.path.join(runtime_root, package_id, module_id)
        instance_runtime_dir = os.path.join(
            runtime_root,
            *external_tool_instance_runtime_parts(package_id, module_id, resolved_instance_id),
        )
        context.update({
            'id': tool_id,
            'tool_id': tool_id,
            'module_id': module_id,
            'module_name': str(meta.get('name') or module_id),
            'module_display_name': str(meta.get('display_name') or module_id),
            'display_name': str(meta.get('display_name') or tool_id),
            'side': str(side or '').strip().lower(),
            'tool_runtime_dir': tool_runtime_dir,
            'instance_id': resolved_instance_id,
            'instance_name': params.get('instance_name') or resolved_instance_id,
            'instance_runtime_dir': instance_runtime_dir,
            'state_file': os.path.join(instance_runtime_dir, 'state.json'),
        })
        context.update(params or {})
        context['instance_id'] = resolved_instance_id
        context['instance_runtime_dir'] = instance_runtime_dir
        context['state_file'] = os.path.join(instance_runtime_dir, 'state.json')
        return context
    def build_client_package_context(self, package: dict, platform_alias: str, arch: str) -> dict:
        context = self._package_base_context(
            package,
            install_root=EXTERNAL_TOOLS_INSTALL_ROOT,
            runtime_root=EXTERNAL_TOOLS_RUNTIME_ROOT,
            platform_alias=platform_alias,
            arch=arch,
        )
        return self._preserve_client_path_context(package, context)
    def build_client_context(self, meta: dict, params: dict, instance_id: str = '', platform_alias: str = '', arch: str = '') -> dict:
        context = self._module_base_context(
            meta,
            params,
            install_root=EXTERNAL_TOOLS_INSTALL_ROOT,
            runtime_root=EXTERNAL_TOOLS_RUNTIME_ROOT,
            instance_id=instance_id,
            side='client',
            platform_alias=platform_alias,
            arch=arch,
        )
        package = meta.get('package_meta') if isinstance(meta.get('package_meta'), dict) else self.catalog_service.get_package(meta.get('package_id') or '')
        return self._preserve_client_path_context(package, context)
    def _preserve_client_path_context(self, package: dict, context: dict) -> dict:
        """Keep client payload paths relative to the client home.

        The server may render payloads on a different machine from the target
        client. Do not expand ``~`` while building client argv/bin paths on the
        server, otherwise payloads can leak the server user's home directory.
        The client expands these paths when executing the payload.
        """
        install_dir = str(context.get('install_dir') or '').strip()
        package_key = str(context.get('package_key') or '').strip()
        rel_execs = {}
        raw_bins = {}
        for exec_name in (package.get('execs') or {}).keys():
            try:
                rel_path = self.catalog_service.resolve_exec_rel_path(package, exec_name, package_key)
            except Exception:
                continue
            rel_path = str(rel_path or '').strip().lstrip('/\\')
            rel_execs[exec_name] = rel_path
            raw_bins[exec_name] = os.path.join(install_dir, rel_path)
        context['exec'] = rel_execs
        context['bin'] = raw_bins
        for name, path in raw_bins.items():
            safe = re.sub(r'[^A-Za-z0-9_]+', '_', name).strip('_')
            context[f'exec_{safe}'] = rel_execs.get(name) or ''
            context[f'bin_{safe}'] = path
        return context
    def _assert_package_usable(self, package: dict, platform_alias: str = '', arch: str = ''):
        platform_value, arch_value = self._require_target(platform_alias, arch, f'package {package.get("id") or "unknown"}')
        self._select_package_key(package, platform_value, arch_value)
