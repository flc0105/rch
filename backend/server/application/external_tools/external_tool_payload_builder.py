import base64
import json
import logging
import os
import shlex

from core.external_tools.payload import (
    client_action_payload,
    client_exec_payload as build_shared_client_exec_payload,
    client_install_payload as build_shared_client_install_payload,
    client_module_payload as build_shared_client_module_payload,
    config_payload_from_rendered,
)
from server.application.external_tools.external_tool_runtime_component import ExternalToolRuntimeComponent


logger = logging.getLogger(__name__)


class ExternalToolClientPayloadBuilder(ExternalToolRuntimeComponent):
    """Build client-side external tool payloads without dispatching commands."""

    def __init__(self, core, context_runtime, install_support, process_state):
        super().__init__(core)
        self.context_runtime = context_runtime
        self.install_support = install_support
        self.process_state = process_state

    def encode_payload_arg(self, payload: dict) -> str:
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        encoded = base64.urlsafe_b64encode(raw).decode('utf-8')
        return f'__json__:{encoded}'

    def _client_download_url(self, filename: str, package_file: dict) -> str:
        download_url = str(package_file.get('download_url') or '').strip()
        if not download_url:
            download_url = f'/api/external-tools/packages/{filename}'
        return download_url

    def _exec_launcher(self, package: dict, exec_name: str) -> dict:
        execs = package.get('execs') if isinstance(package.get('execs'), dict) else {}
        exec_item = execs.get(exec_name) if isinstance(execs.get(exec_name), dict) else {}
        launcher = exec_item.get('launcher')
        return dict(launcher) if isinstance(launcher, dict) else {}

    @staticmethod
    def _launcher_override(value) -> dict:
        if not isinstance(value, dict):
            return {}
        executable = str(value.get('executable') or '').strip()
        return {'executable': executable} if executable else {}

    def build_client_launcher_payload(self, meta: dict, platform_alias: str = '', arch: str = '') -> dict:
        package = meta.get('package_meta') or self.catalog_service.get_package(meta.get('package_id') or '')
        platform_value, arch_value = self._require_target(
            platform_alias,
            arch,
            f'client launcher {meta.get("tool_id") or meta.get("id") or "unknown"}',
        )
        exec_name = self.install_support._primary_exec_name(package, meta)
        launcher = self._exec_launcher(package, exec_name)
        if not launcher or str(launcher.get('type') or 'direct').strip().lower() in ('', 'direct'):
            raise ValueError('external tool module does not use a configurable launcher')
        return {
            'action': 'resolve_launcher',
            'tool_id': meta.get('tool_id') or '',
            'package_id': meta.get('package_id') or package.get('id') or '',
            'module_id': meta.get('id') or '',
            'platform': platform_value,
            'arch': arch_value,
            'launcher': launcher,
        }

    def build_client_install_payload(self, package: dict, platform_alias: str, arch: str) -> dict:
        platform_value, arch_value = self._require_target(platform_alias, arch, f'client package {package.get("id") or "unknown"}')
        logger.info(
            '[external-tools] build client install payload: package_id=%s target=%s/%s',
            package.get('id') or '',
            platform_value,
            arch_value,
        )
        context = self.context_runtime.build_client_package_context(package, platform_alias=platform_value, arch=arch_value)
        package_file = self._package_file(package, context.get('package_key') or '')
        filename = str(package_file.get('filename') or '').strip()
        if not filename:
            raise ValueError('platform package filename is required')
        exec_name = self.install_support._primary_exec_name(package)
        rel_path = (context.get('exec') or {}).get(exec_name) or ''
        return build_shared_client_install_payload(
            package,
            context,
            source=self._package_source(package, context.get('package_key') or ''),
            filename=filename,
            download_url=self._client_download_url(filename, package_file),
            executable_rel_path=rel_path,
            skip_if_exists=self.install_support._client_skip_path(package, context),
            action='install',
        )

    def build_client_start_payload(self, meta: dict, params: dict | None = None, instance_id: str = '', install_if_needed: bool = False, require_required_params: bool = True, platform_alias: str = '', arch: str = '', launcher_override: dict | None = None) -> dict:
        del install_if_needed
        package = meta.get('package_meta') or self.catalog_service.get_package(meta.get('package_id') or '')
        platform_value, arch_value = self._require_target(platform_alias, arch, f'client module {meta.get("tool_id") or meta.get("id") or "unknown"}')
        logger.info(
            '[external-tools] build client start payload: tool_id=%s target=%s/%s',
            meta.get('tool_id') or meta.get('id') or '',
            platform_value,
            arch_value,
        )
        resolved_params = self.resolve_params(meta, params, require_required=require_required_params)
        context = self.context_runtime.build_client_context(meta, resolved_params, instance_id=instance_id, platform_alias=platform_value, arch=arch_value)
        package_file = self._package_file(package, context.get('package_key') or '')
        filename = str(package_file.get('filename') or '').strip()
        if not filename:
            raise ValueError('platform package filename is required')
        rendered_meta = self._render_value(meta, context)
        runtime = self._render_value(self._module_runtime_for_platform(meta, context.get('platform') or '', context.get('arch') or ''), context)
        runtime.setdefault('state_file', context.get('state_file') or '')
        runtime_argv = runtime.get('argv') or []
        if isinstance(runtime_argv, str):
            runtime_argv = shlex.split(runtime_argv)
        if isinstance(runtime_argv, list):
            runtime['argv'] = self._append_runtime_extra_args(runtime_argv, runtime, context)
        config_payload = config_payload_from_rendered(rendered_meta, lambda value: self._render_value(value, context))
        exec_name = self.install_support._primary_exec_name(package, meta)
        rel_path = (context.get('exec') or {}).get(exec_name) or ''
        payload = build_shared_client_module_payload(
            meta,
            context,
            action='start',
            source=self._package_source(package, context.get('package_key') or ''),
            filename=filename,
            download_url=self._client_download_url(filename, package_file),
            executable_rel_path=rel_path,
            skip_if_exists=self.install_support._client_skip_path(package, context, module=meta),
            params=resolved_params,
            runtime=runtime,
            config=config_payload,
            lifecycle=rendered_meta.get('lifecycle') or {},
            install_if_needed=False,
        )
        launcher = self._exec_launcher(package, exec_name)
        if launcher:
            payload['launcher'] = launcher
            override = self._launcher_override(launcher_override)
            if override:
                payload['launcher_override'] = override
        return payload

    def build_client_oneshot_payload(self, meta: dict, params: dict | None = None, platform_alias: str = '', arch: str = '') -> dict:
        if str(meta.get('execution') or '').strip().lower() != 'oneshot':
            raise ValueError(f'module {meta.get("tool_id") or meta.get("id") or "unknown"} execution is not oneshot')
        package = meta.get('package_meta') or self.catalog_service.get_package(meta.get('package_id') or '')
        platform_value, arch_value = self._require_target(platform_alias, arch, f'client oneshot {meta.get("tool_id") or meta.get("id") or "unknown"}')
        logger.info(
            '[external-tools] build client oneshot payload: tool_id=%s target=%s/%s',
            meta.get('tool_id') or meta.get('id') or '',
            platform_value,
            arch_value,
        )
        resolved_params = self.resolve_params(meta, params, require_required=True)
        run_id = self.process_state._make_oneshot_run_id(meta)
        context = self.context_runtime.build_client_context(meta, resolved_params, instance_id=run_id, platform_alias=platform_value, arch=arch_value)
        context = self.process_state._apply_client_oneshot_context(context, meta, run_id)
        package_file = self._package_file(package, context.get('package_key') or '')
        filename = str(package_file.get('filename') or '').strip()
        if not filename:
            raise ValueError('platform package filename is required')
        rendered_meta = self._render_value(meta, context)
        runtime = self._render_value(self._module_runtime_for_platform(meta, context.get('platform') or '', context.get('arch') or ''), context)
        runtime.setdefault('state_file', context.get('state_file') or '')
        runtime_argv = runtime.get('argv') or []
        if isinstance(runtime_argv, str):
            runtime_argv = shlex.split(runtime_argv)
        if isinstance(runtime_argv, list):
            runtime['argv'] = self._append_runtime_extra_args(runtime_argv, runtime, context)
        config_payload = config_payload_from_rendered(rendered_meta, lambda value: self._render_value(value, context))
        exec_name = self.install_support._primary_exec_name(package, meta)
        rel_path = (context.get('exec') or {}).get(exec_name) or ''
        payload = build_shared_client_module_payload(
            meta,
            context,
            action='oneshot',
            source=self._package_source(package, context.get('package_key') or ''),
            filename=filename,
            download_url=self._client_download_url(filename, package_file),
            executable_rel_path=rel_path,
            skip_if_exists=self.install_support._client_skip_path(package, context, module=meta),
            params=resolved_params,
            runtime=runtime,
            config=config_payload,
            install_if_needed=False,
            execution='oneshot',
            run_id=run_id,
            timeout_sec=self.process_state._oneshot_timeout_sec(meta, runtime),
        )
        launcher = self._exec_launcher(package, exec_name)
        if launcher:
            payload['launcher'] = launcher
        return payload

    def build_client_payload(self, meta: dict, params: dict | None = None) -> dict:
        return self.build_client_start_payload(meta, params=params)

    def build_client_action_payload(self, meta: dict, action: str, instance_id: str = '', params: dict | None = None, max_bytes: int | None = None) -> dict:
        resolved_params = self.resolve_params(meta, params or {}, require_required=False) if params else {}
        # Action payloads only need deterministic runtime path from package/module/instance.
        package_id = meta.get('package_id') or ''
        module_id = meta.get('id') or ''
        sanitized = self._sanitize_instance_id(instance_id)
        runtime_dir = os.path.join('~/.ops/external_tools/runtime', package_id, module_id, 'instances', sanitized)
        runtime = {'pid_file': os.path.join(runtime_dir, 'tool.pid'), 'stdout': os.path.join(runtime_dir, 'stdout.log'), 'stderr': 'stdout', 'state_file': os.path.join(runtime_dir, 'state.json')}
        return client_action_payload(
            meta,
            action=action,
            instance_id=sanitized,
            params=resolved_params,
            runtime=runtime,
            max_bytes=int(max_bytes or self.DEFAULT_LOG_TAIL_BYTES),
        )

    def build_client_install_status_payloads(self, packages: list[dict], platform_alias: str = '', arch: str = '') -> list[dict]:
        payloads = []
        for package in packages or []:
            try:
                payload = self.build_client_install_payload(package, platform_alias=platform_alias, arch=arch)
                payload['action'] = 'install_status'
                payloads.append(payload)
            except Exception as e:
                payloads.append({'action': 'install_status', 'tool_id': package.get('id') or '', 'package_id': package.get('id') or '', 'display_name': package.get('display_name') or package.get('id') or '', 'side': 'client', 'error': str(e)})
        return payloads

    def build_client_exec_payload(self, target: dict, raw_args: str = '', platform_alias: str = '', arch: str = '', cwd: str = '') -> dict:
        package = target.get('package_meta') or {}
        exec_item = target.get('exec_item') if isinstance(target.get('exec_item'), dict) else {}
        exec_options = target.get('exec_options') if isinstance(target.get('exec_options'), dict) else {}
        exec_name = target.get('exec_name') or ''
        platform_value, arch_value = self._require_target(platform_alias, arch, f'client exec {exec_name or "unknown"}')
        logger.info(
            '[external-tools] build client exec payload: package_id=%s exec=%s target=%s/%s',
            package.get('id') or '',
            exec_name,
            platform_value,
            arch_value,
        )
        context = self.context_runtime.build_client_package_context(package, platform_alias=platform_value, arch=arch_value)
        package_file = self._package_file(package, context.get('package_key') or '')
        filename = str(package_file.get('filename') or '').strip()
        rel_path = self.catalog_service.resolve_exec_rel_path(package, exec_name, context.get('package_key') or '')
        payload_exec_options = {
            'arg_mode': exec_options.get('arg_mode') or exec_item.get('arg_mode') or 'raw_append',
            'cwd': cwd or exec_options.get('cwd') or exec_item.get('cwd') or '',
            'timeout_sec': exec_options.get('timeout_sec') if exec_options.get('timeout_sec') is not None else exec_item.get('timeout_sec'),
        }
        launcher = self._exec_launcher(package, exec_name)
        if launcher:
            payload_exec_options['launcher'] = launcher
        return build_shared_client_exec_payload(
            package,
            context,
            source=self._package_source(package, context.get('package_key') or ''),
            filename=filename,
            download_url=self._client_download_url(filename, package_file),
            executable_rel_path=rel_path,
            skip_if_exists=self.install_support._client_skip_path(package, context),
            exec_name=exec_name,
            exec_options=payload_exec_options,
            raw_args=raw_args,
        )
