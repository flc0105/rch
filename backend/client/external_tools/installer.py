import os
import shutil

from client.external_tools.common import ExternalToolCommon
from core.external_tools.payload import client_install_status_error_payload, client_install_status_result
from core.external_tools.archive import safe_extract_zip_archive
from core.external_tools.paths import EXTERNAL_TOOLS_INSTALL_ROOT


class ExternalToolInstaller(ExternalToolCommon):
    """Install, uninstall and install-status operations for external tool packages."""

    def install_log_path(self, install_dir: str) -> str:
        return os.path.join(self.expand_path(install_dir), '.install.log')

    def read_install_log(self, install_dir: str) -> str:
        path = self.install_log_path(install_dir)
        if not os.path.isfile(path):
            return ''
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                return fh.read()
        except OSError:
            return ''

    def write_install_log(self, install_dir: str, lines) -> str:
        content = '\n'.join(str(line) for line in (lines or []) if str(line or '').strip())
        if not content:
            return ''
        try:
            os.makedirs(self.expand_path(install_dir), exist_ok=True)
            with open(self.install_log_path(install_dir), 'w', encoding='utf-8') as fh:
                fh.write(content)
                fh.write('\n')
        except OSError:
            pass
        return content

    def install_status_payload(self, payload: dict) -> dict:
        self.validate_package_payload(payload, 'install-status')
        install = payload.get('install') or {}
        install_dir = self.expand_path(
            install.get('install_dir') or os.path.join(EXTERNAL_TOOLS_INSTALL_ROOT, 'unknown')
        )
        skip_if_exists = self.expand_path(install.get('skip_if_exists') or install_dir)

        package = payload.get('package') or {}
        executable_rel_path = str(package.get('executable_rel_path') or '').strip()
        executable_path = (
            self.expand_path(os.path.join(install_dir, executable_rel_path))
            if executable_rel_path
            else skip_if_exists
        )
        exec_paths = {}
        raw_exec_paths = package.get('exec_paths') if isinstance(package.get('exec_paths'), dict) else {}
        for name, rel_path in raw_exec_paths.items():
            rel_text = str(rel_path or '').strip().lstrip('/\\')
            if not rel_text:
                continue
            exec_paths[str(name)] = self.expand_path(os.path.join(install_dir, rel_text))

        # Strict FS-driven package status. This intentionally ignores old state
        # files and frontend cache: deleting install_dir must make installed False.
        install_dir_exists = os.path.isdir(install_dir)
        missing_execs = {name: path for name, path in exec_paths.items() if not os.path.isfile(path)} if install_dir_exists else dict(exec_paths)
        cache = self.cache_info(payload)
        commands = self.build_command_map(exec_paths)

        return client_install_status_result(
            payload,
            install_dir=install_dir,
            install_dir_exists=install_dir_exists,
            skip_if_exists=skip_if_exists,
            executable_path=executable_path,
            exec_paths=exec_paths,
            missing_execs=missing_execs,
            cache=cache,
            commands=commands,
            install_log=self.read_install_log(install_dir),
            install_log_path=self.install_log_path(install_dir),
        )

    def install_if_needed(self, payload: dict, package_info) -> dict:
        self.validate_package_payload(payload, 'install')
        status = self.install_status_payload(payload)
        install_dir = status['install_dir']
        already_installed = bool(status['installed'])
        extracted = False
        package_info = package_info if isinstance(package_info, dict) else {'archive_path': str(package_info or ''), 'source': 'unknown'}
        archive_path = package_info.get('archive_path') or package_info.get('cache_path') or ''
        install_log = [
            f'Package: {payload.get("display_name") or payload.get("package_id") or payload.get("tool_id") or "external tool"}',
            f'Target: {payload.get("side") or "client"} {payload.get("platform") or ""} {payload.get("arch") or ""}'.rstrip(),
            f'Platform package key: {payload.get("package_key") or "-"}',
            f'Install dir: {install_dir}',
            f'Package source: {package_info.get("source") or "unknown"}',
            f'Package cache: {archive_path or "-"}',
        ]

        if not already_installed:
            if not archive_path:
                raise ValueError('package archive path is required')
            os.makedirs(install_dir, exist_ok=True)
            install_log.append(f'Extracting package to: {install_dir}')
            safe_extract_zip_archive(archive_path, install_dir, self.expand_path)
            extracted = True
        else:
            install_log.append('Existing installation is valid; extraction skipped.')

        # Re-read after extraction. Do not report success if the configured marker
        # still does not exist; otherwise the UI will flip back to not installed on
        # the next refresh.
        status = self.install_status_payload(payload)
        if not status.get('installed'):
            missing = status.get('missing_execs') or {}
            install_log.append(f'Validation failed; missing execs: {missing or "-"}')
            self.write_install_log(install_dir, install_log)
            if missing:
                raise FileNotFoundError(f'Package was extracted but configured executable paths were not found: {missing}')
            raise FileNotFoundError(f'Package was extracted but install directory was not found: {status.get("install_dir") or install_dir}')

        executable_path = status.get('executable_path') or ''
        self.chmod(executable_path)
        for name, path in (status.get('exec_paths') or {}).items():
            self.chmod(path)
            install_log.append(f'Validated exec {name}: {path}')

        source = package_info.get('source') or 'unknown'
        persisted_install_log = self.write_install_log(install_dir, install_log)
        status.update({
            'installed': True,
            'already_installed': already_installed,
            'extracted': extracted,
            'package_source': source,
            'used_cache': source == 'cache',
            'downloaded': source == 'download',
            'package': archive_path,
            'cache': self.cache_info(payload),
            'install_log': persisted_install_log,
            'message': 'already installed' if already_installed else 'installed successfully',
        })

        return status

    def install_payload(self, payload: dict) -> dict:
        package_info = self.download_package(payload)
        install_info = self.install_if_needed(payload, package_info)
        source_label = 'cached package' if install_info.get('used_cache') else 'downloaded package' if install_info.get('downloaded') else 'existing package'
        install_info['message'] = f'{payload.get("display_name") or payload.get("tool_id") or "external tool"} installed from {source_label}'
        return install_info

    def install_statuses_payload(self, payload) -> dict:
        if isinstance(payload, list):
            tools = payload
        elif isinstance(payload, dict):
            tools = payload.get('tools') or []
        else:
            raise ValueError('Invalid external tool payload')

        if not isinstance(tools, list):
            raise ValueError('Invalid external tool tools payload')

        items = []
        for tool_payload in tools:
            if not isinstance(tool_payload, dict):
                continue

            try:
                if tool_payload.get('error'):
                    raise ValueError(str(tool_payload.get('error')))
                items.append(self.install_status_payload(tool_payload))
            except Exception as e:
                items.append(client_install_status_error_payload(tool_payload, e))

        return {'items': items}

    def write_config(self, payload: dict) -> dict:
        config = payload.get('config') or {}
        target = str(config.get('target') or '').strip()
        if not target:
            return {}

        content = str(config.get('content') or '')
        target_path = self.expand_path(target)

        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, 'w', encoding='utf-8') as file_obj:
            file_obj.write(content)

        return {'target': target_path, 'size': os.path.getsize(target_path)}

    def uninstall_payload(self, payload: dict) -> dict:
        tool_id = payload.get('tool_id') or ''
        package_id = payload.get('package_id') or tool_id
        if not package_id:
            raise ValueError('package_id is required')

        if self.has_running_instances_for_package(package_id):
            raise ValueError('This package has running instances on this machine. Stop them before uninstalling.')

        status = self.install_status_payload(payload)
        install_dir = status.get('install_dir') or ''

        removed = False
        if install_dir and os.path.isdir(install_dir):
            shutil.rmtree(install_dir)
            removed = True

        status.update({
            'installed': False,
            'removed': removed,
            'message': (
                f'{payload.get("display_name") or tool_id} uninstalled from {install_dir}'
                if removed
                else f'{payload.get("display_name") or tool_id} was not installed at {install_dir}'
            ),
        })

        return status
