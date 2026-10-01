import logging
from typing import Any

from core.external_tools.paths import (
    expand_path,
    is_url_like,
    sanitize_instance_id,
    should_expand_argv_item,
)
from core.external_tools.params import resolve_params as resolve_external_tool_params
from core.platform.normalization import normalize_arch, normalize_platform
from core.external_tools.runtime import missing_exec_paths as find_missing_exec_paths
from core.external_tools.runtime import resolved_exec_context as build_resolved_exec_context
from core.external_tools.runtime import select_module_runtime_for_platform
from core.external_tools.target import require_target as require_external_tool_target
from core.external_tools.template import append_runtime_extra_args, context_get, render_value, split_extra_argv


logger = logging.getLogger(__name__)


class ExternalToolRuntimeBase:
    """Constructor and low-level helpers shared by focused runtime mixins."""

    DEFAULT_LOG_TAIL_BYTES = 65536

    def __init__(
        self,
        catalog_service,
        command_execution_api,
        remote_execution_service=None,
    ):
        self.catalog_service = catalog_service
        self.command_execution_api = command_execution_api
        self.remote_execution_service = remote_execution_service
    def _normalize_platform(self, value: Any = '') -> str:
        return normalize_platform(value or '')
    def _normalize_arch(self, value: Any = '') -> str:
        return normalize_arch(value or '')
    def _require_target(self, platform_alias: Any, arch: Any, context: str) -> tuple[str, str]:
        return require_external_tool_target(platform_alias, arch, context)
    def _context_get(self, context: dict, dotted_key: str) -> Any:
        return context_get(context, dotted_key)
    def _render_value(self, value: Any, context: dict) -> Any:
        return render_value(value, context)
    def _split_extra_argv(self, value: Any) -> list[str]:
        return split_extra_argv(value)
    def _append_runtime_extra_args(self, argv: list[str], runtime: dict, context: dict) -> list[str]:
        return append_runtime_extra_args(argv, runtime, context)
    def _expand_path(self, path: str) -> str:
        return expand_path(path)
    def _is_url_like(self, value: str) -> bool:
        return is_url_like(value)
    def _should_expand_argv_item(self, value: str, index: int) -> bool:
        return should_expand_argv_item(value, index)
    def _sanitize_instance_id(self, value: Any) -> str:
        return sanitize_instance_id(value)
    def resolve_params(self, meta: dict, params: dict | None, require_required: bool = True) -> dict:
        return resolve_external_tool_params(meta, params, require_required=require_required)
    def _select_package_key(self, package: dict, platform_alias: str = '', arch: str = '') -> str:
        return self.catalog_service.select_package_key(package, platform_alias=platform_alias, arch=arch)
    def _package_file(self, package: dict, package_key: str) -> dict:
        files = package.get('platform_packages') if isinstance(package.get('platform_packages'), dict) else {}
        info = files.get(package_key)
        if not isinstance(info, dict):
            raise ValueError(f'package build not found: {package_key}')
        return info
    def _package_source(self, package: dict, package_key: str) -> str:
        package_file = self._package_file(package, package_key)
        return str(package_file.get('source') or package.get('source') or '').strip()
    def _module_runtime_for_platform(self, module: dict, platform_alias: str, arch: str) -> dict:
        return select_module_runtime_for_platform(module, platform_alias, arch)
    def _resolved_exec_context(self, package: dict, package_key: str, install_dir: str) -> tuple[dict, dict]:
        return build_resolved_exec_context(
            package,
            package_key,
            install_dir,
            self.catalog_service.resolve_exec_rel_path,
            self._expand_path,
        )
    def _missing_exec_paths(self, abs_bins: dict) -> dict:
        return find_missing_exec_paths(abs_bins, self._expand_path)
