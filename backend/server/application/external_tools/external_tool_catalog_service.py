import glob
import json
import logging
import os
from copy import deepcopy
from typing import Any

from core.external_tools.meta import normalize_meta as normalize_external_tool_meta
from core.platform.normalization import normalize_arch, normalize_platform, platform_key
from core.external_tools.selector import (
    package_arch_matches,
    package_platform_matches,
    resolve_exec_rel_path,
    select_package_key,
)


logger = logging.getLogger(__name__)


class ExternalToolCatalogService:
    """
    External tool package catalog.

    v2 convention:
    - one meta file describes one installable package
    - package may expose multiple daemon modules under modules[]
    - package may expose multiple CLI execs under execs{}
    - platform/arch selection is resolved from platform_packages{}
    - side is no longer a capability constraint; target host decides platform/arch
    """

    def __init__(self, metas_root_dir: str, packages_root_dir: str):
        self.metas_root_dir = os.path.abspath(metas_root_dir)
        self.packages_root_dir = os.path.abspath(packages_root_dir)
        os.makedirs(self.metas_root_dir, exist_ok=True)
        os.makedirs(self.packages_root_dir, exist_ok=True)

    def _read_json_file(self, path: str) -> dict:
        with open(path, 'r', encoding='utf-8') as file_obj:
            data = json.load(file_obj)
        if not isinstance(data, dict):
            raise ValueError(f'Invalid external tool meta: {path}')
        return data

    def _normalize_platform(self, value: Any) -> str:
        return normalize_platform(value)

    def _normalize_arch(self, value: Any) -> str:
        return normalize_arch(value)

    def _platform_key(self, platform_alias: str, arch: str) -> str:
        return platform_key(platform_alias, arch)

    def normalize_meta(self, meta: dict, path: str = '') -> dict:
        return normalize_external_tool_meta(meta, path=path)

    def list_packages(self) -> list[dict]:
        items = []
        pattern = os.path.join(self.metas_root_dir, '**/*.json')
        for path in sorted(glob.iglob(pattern, recursive=True)):
            if not os.path.isfile(path):
                continue
            try:
                items.append(self.normalize_meta(self._read_json_file(path), path=path))
            except Exception as e:
                items.append({
                    'id': os.path.splitext(os.path.basename(path))[0],
                    'display_name': os.path.basename(path),
                    'description': f'Invalid meta: {e}',
                    'platforms': [],
                    'arches': [],
                    'modules': [],
                    'execs': {},
                    'error': str(e),
                    '_meta_path': os.path.abspath(path),
                })
        return items

    def list_tools(self) -> list[dict]:
        """Return runnable module records."""
        modules = []
        for package in self.list_packages():
            if package.get('error'):
                continue
            for module in package.get('modules') or []:
                row = deepcopy(module)
                row['package'] = self.public_package_ref(package)
                row['package_meta'] = package
                modules.append(row)
        return modules

    def get_catalog(self) -> dict:
        return {
            'items': self.list_packages(),
            'modules': self.list_tools(),
        }

    def get_package(self, package_id: str) -> dict:
        target = str(package_id or '').strip()
        if not target:
            raise ValueError('package_id is required')
        for item in self.list_packages():
            if str(item.get('id') or '').strip() == target:
                if item.get('error'):
                    raise ValueError(item.get('error'))
                return item
        raise FileNotFoundError(f'External tool package not found: {package_id}')

    def get_tool(self, tool_id: str) -> dict:
        target = str(tool_id or '').strip()
        if not target:
            raise ValueError('tool_id is required')
        for item in self.list_tools():
            if str(item.get('tool_id') or item.get('id') or '').strip() == target:
                return item
        raise FileNotFoundError(f'External tool module not found: {tool_id}')

    def get_module(self, tool_id: str) -> dict:
        return self.get_tool(tool_id)

    def public_package_ref(self, package: dict) -> dict:
        return {
            'id': package.get('id') or '',
            'name': package.get('name') or package.get('id') or '',
            'display_name': package.get('display_name') or package.get('id') or '',
            'version': package.get('version') or '',
            'platforms': package.get('platforms') or [],
            'arches': package.get('arches') or [],
            'package_keys': package.get('package_keys') or [],
        }

    def select_package_key(self, package: dict, platform_alias: str = '', arch: str = '') -> str:
        return select_package_key(package, platform_alias=platform_alias, arch=arch, log=logger)

    def resolve_exec_rel_path(self, package: dict, exec_name: str, package_key: str) -> str:
        return resolve_exec_rel_path(package, exec_name, package_key)

    def get_meta_path(self, package_id: str) -> str:
        meta = self.get_package(package_id)
        path = os.path.abspath(str(meta.get('_meta_path') or '').strip())
        if not path:
            raise FileNotFoundError(f'External tool meta not found: {package_id}')
        if os.path.commonpath([self.metas_root_dir, path]) != self.metas_root_dir:
            raise ValueError('invalid external tool meta path')
        if not os.path.isfile(path):
            raise FileNotFoundError(f'External tool meta not found: {package_id}')
        return path

    def read_meta_content(self, package_id: str) -> dict:
        path = self.get_meta_path(package_id)
        with open(path, 'r', encoding='utf-8') as file_obj:
            content = file_obj.read()
        return {
            'tool_id': package_id,
            'package_id': package_id,
            'path': path,
            'name': os.path.basename(path),
            'content': content,
            'size': len(content.encode('utf-8')),
        }

    def save_meta_content(self, package_id: str, content: str) -> dict:
        path = self.get_meta_path(package_id)
        text = str(content or '')
        try:
            parsed = json.loads(text)
        except Exception as e:
            raise ValueError(f'Invalid JSON meta: {e}')
        if not isinstance(parsed, dict):
            raise ValueError('Invalid JSON meta: expected object')

        normalized = self.normalize_meta(parsed, path=path)
        new_package_id = str(normalized.get('id') or '').strip()
        if new_package_id and new_package_id != str(package_id or '').strip():
            raise ValueError('Changing external tool package id is not supported from this editor')

        with open(path, 'w', encoding='utf-8') as file_obj:
            file_obj.write(text)
        return {
            'tool_id': package_id,
            'package_id': package_id,
            'path': path,
            'name': os.path.basename(path),
            'size': len(text.encode('utf-8')),
        }

    def get_package_path(self, filename: str) -> str:
        safe_name = os.path.basename(str(filename or '').strip())
        if not safe_name:
            raise ValueError('filename is required')
        path = os.path.abspath(os.path.join(self.packages_root_dir, safe_name))
        if os.path.commonpath([self.packages_root_dir, path]) != self.packages_root_dir:
            raise ValueError('invalid package filename')
        if not os.path.isfile(path):
            raise FileNotFoundError(f'External tool package not found: {safe_name}')
        return path

    def get_package_download_filename(self, package_id: str, platform_alias: str = '', arch: str = '') -> str:
        package = self.get_package(package_id)
        key = self.select_package_key(package, platform_alias=platform_alias, arch=arch)
        info = (package.get('platform_packages') or {}).get(key) or {}
        filename = str(info.get('filename') or '').strip()
        if not filename:
            raise ValueError(f'package {package_id} has no filename for {key}')
        return filename

    def _platform_matches(self, package: dict, platform_alias: str = '') -> bool:
        return package_platform_matches(package, platform_alias)

    def _arch_matches(self, package: dict, arch: str = '') -> bool:
        return package_arch_matches(package, arch)

    def list_exec_targets(self, platform_alias: str = '', arch: str = '') -> list[dict]:
        target_platform = self._normalize_platform(platform_alias or '')
        target_arch = self._normalize_arch(arch or '')
        if not target_platform or not target_arch:
            raise ValueError(f'target platform and arch are required for external tool execs, got {target_platform or "unknown"}/{target_arch or "unknown"}')

        items = []
        for package in self.list_packages():
            if package.get('error'):
                continue
            if not self._platform_matches(package, platform_alias):
                continue
            if not self._arch_matches(package, arch):
                continue
            try:
                package_key = self.select_package_key(package, platform_alias=platform_alias, arch=arch)
            except Exception as e:
                logger.warning(
                    '[external-tools] skip exec target because target selection failed: package_id=%s target=%s/%s error=%s',
                    package.get('id') or '',
                    target_platform or 'unknown',
                    target_arch or 'unknown',
                    e,
                )
                continue

            for exec_name, exec_item in (package.get('execs') or {}).items():
                if not isinstance(exec_item, dict) or not exec_item.get('enabled', True):
                    continue
                rel_path = str((exec_item.get('paths') or {}).get(package_key) or '').strip()
                if not rel_path:
                    continue
                items.append({
                    'exec_name': exec_name,
                    'package_id': package.get('id') or '',
                    'display_name': package.get('display_name') or package.get('id') or '',
                    'description': exec_item.get('description') or package.get('description') or '',
                    'package_key': package_key,
                    'executable_rel_path': rel_path,
                    'package_meta': package,
                    'exec_item': exec_item,
                    'exec_options': {
                        'arg_mode': exec_item.get('arg_mode') or 'raw_append',
                        'cwd': exec_item.get('cwd') or '',
                        'timeout_sec': exec_item.get('timeout_sec'),
                    },
                })

        return sorted(items, key=lambda item: (item.get('exec_name') or '').lower())

    def resolve_exec_target(self, exec_name: str, platform_alias: str = '', arch: str = '') -> dict:
        target = str(exec_name or '').strip()
        if not target:
            raise ValueError('external tool exec name is required')

        matches = [
            item for item in self.list_exec_targets(platform_alias=platform_alias, arch=arch)
            if item.get('exec_name') == target
        ]

        if not matches:
            raise FileNotFoundError(f'External tool exec not found: {target}')

        if len(matches) > 1:
            lines = [f'Ambiguous external tool exec: {target}', '', 'Matched:']
            for item in matches:
                lines.append(f'- {item.get("exec_name")} -> {item.get("package_id")}')
            lines.append('Keep exec names unique for the current platform/arch.')
            raise ValueError('\n'.join(lines))

        return matches[0]
