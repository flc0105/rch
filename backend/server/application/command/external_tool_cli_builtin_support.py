"""Server-side External Tool CLI: package, module, instance and public exec."""

import json
import logging
import re
import shlex
import time

from core.external_tools.install_status import is_installed_status, normalize_install_status
from core.protocol.structured_arg_codec import encode_structured_arg
from core.utils.command_output import StructuredCommandResult, render_structured_result


class ExternalToolCliBuiltinSupport:
    """
    xt 轻量 CLI 门面。

    约束：
    - Exec 只解析 package.execs 暴露的原生命令，原生 argv 不被改写。
    - Package / Instance 复用既有 Client 操作并根据真实状态确认转移。
    - 状态变化通过现有 External Tool lifecycle / Notification 管线广播。
    """

    def __init__(self, server, conn, command_processor_factory, history_entry_id_provider):
        self.server = server
        self.conn = conn
        self.command_processor_factory = command_processor_factory
        self.history_entry_id_provider = history_entry_id_provider

    def _history(self):
        return getattr(self.server, 'command_history_orchestrator', None)

    def _suppress_query_history(self):
        history = self._history()
        if history is not None:
            history.suppress_xt_query(self.conn, self.history_entry_id_provider())

    def _catalog_service(self):
        web_service = getattr(self.server, 'web_service', None)
        assembly = getattr(web_service, 'assembly', None)
        service = getattr(assembly, 'external_tool_catalog_service', None)
        if service is None:
            raise RuntimeError('external tool catalog service is not available')
        return service

    def _runtime_service(self):
        web_service = getattr(self.server, 'web_service', None)
        assembly = getattr(web_service, 'assembly', None)
        service = getattr(assembly, 'external_tool_runtime_service', None)
        if service is None:
            raise RuntimeError('external tool runtime service is not available')
        return service

    def _client_platform(self) -> str:
        info = getattr(self.conn, 'session_info', None)
        value = getattr(info, 'os_alias', '') if info is not None else ''
        normalized = self._catalog_service()._normalize_platform(value or '')
        if not normalized:
            raise ValueError('client platform is required for external tool command resolution')
        return normalized

    def _client_arch(self) -> str:
        info = getattr(self.conn, 'session_info', None)
        value = getattr(info, 'arch', '') if info is not None else ''
        normalized = self._catalog_service()._normalize_arch(value or '')
        if not normalized:
            raise ValueError('client arch is required for external tool command resolution')
        return normalized

    def _client_cwd(self) -> str:
        info = getattr(self.conn, 'session_info', None)
        return str(getattr(info, 'cwd', '') if info is not None else '').strip()

    def _split_first_token(self, text: str) -> tuple[str, str]:
        raw = str(text or '').strip()
        if not raw:
            return '', ''
        parts = raw.split(None, 1)
        first = parts[0].strip()
        rest = parts[1].strip() if len(parts) > 1 else ''
        return first, rest

    def _strip_raw_arg_separator(self, text: str) -> str:
        raw = str(text or '').strip()
        if raw == '--':
            return ''
        if raw.startswith('-- '):
            return raw[3:].strip()
        return raw

    def _resolve_exec_target(self, exec_name: str) -> dict:
        return self._catalog_service().resolve_exec_target(
            exec_name,
            platform_alias=self._client_platform(),
            arch=self._client_arch(),
        )

    def _build_client_payload(self, target: dict, raw_args: str = '') -> dict:
        runtime_service = self._runtime_service()
        payload = runtime_service.payload_builder.build_client_exec_payload(
            target,
            raw_args=self._strip_raw_arg_separator(raw_args),
            platform_alias=self._client_platform(),
            arch=self._client_arch(),
            cwd=self._client_cwd(),
        )
        return payload

    def _iter_nested_command(self, command_text: str):
        command_processor = self.command_processor_factory()
        executor = command_processor(command_text)
        for item in executor():
            yield item

    def _collect_nested_command_text(self, command_text: str) -> tuple[int, str]:
        """执行一个内部 client 命令，并收集文本结果。"""
        status = 1
        chunks = []
        for item_status, item_text in self._iter_nested_command(command_text):
            status = item_status
            if item_text is not None:
                chunks.append(str(item_text))
        return status, ''.join(chunks)

    def _install_status_text(self, item: dict | None) -> str:
        return normalize_install_status(item)

    def _load_cli_install_status_map(self, items: list[dict]) -> dict[tuple[str, str], dict]:
        payloads = []
        keys = []

        for item in items:
            try:
                payload = self._build_client_payload(item, raw_args='')
                package_id = payload.get('package_id') or item.get('package_id') or item.get('tool_id') or ''
                package_key = payload.get('package_key') or item.get('package_key') or ''
                payloads.append(payload)
                keys.append((package_id, package_key))
            except Exception as e:
                package_id = item.get('package_id') or item.get('tool_id') or ''
                package_key = item.get('package_key') or ''
                keys.append((package_id, package_key))
                payloads.append({'error': str(e)})

        if not payloads:
            return {}

        command = f'external_tool_install_statuses {encode_structured_arg({"tools": payloads})}'
        try:
            status, text = self._collect_nested_command_text(command)
            if not status:
                raise RuntimeError(text or 'external_tool_install_statuses failed')
            decoded = json.loads(text or '{}')
            status_items = decoded.get('items') if isinstance(decoded, dict) else decoded
            if not isinstance(status_items, list):
                raise ValueError('invalid install statuses payload')
        except Exception as e:
            return {key: {'installed': False, 'install_status': 'unknown', 'error': str(e)} for key in keys}

        result = {}
        for index, key in enumerate(keys):
            status_item = status_items[index] if index < len(status_items) and isinstance(status_items[index], dict) else {}
            result[key] = status_item
        return result

    def _build_cli_list_payload(self) -> list[dict]:
        catalog = self._catalog_service()
        items = catalog.list_exec_targets(
            platform_alias=self._client_platform(),
            arch=self._client_arch(),
        )

        status_map = self._load_cli_install_status_map(items)
        rows = []
        for item in items:
            package_id = item.get('package_id') or item.get('tool_id') or ''
            package_key = item.get('package_key') or ''
            install_status = self._install_status_text(status_map.get((package_id, package_key)))
            if not is_installed_status(install_status):
                continue
            rows.append({
                'exec_name': item.get('exec_name') or '',
                'package_id': package_id,
            })

        rows.sort(key=lambda item: str(item.get('exec_name') or '').lower())
        return rows

    def _render_cli_list(self, output_format: str):
        rows = self._build_cli_list_payload()
        if not rows and output_format != 'json':
            return 1, 'No installed external tool Exec commands for this Client.'

        display_rows = rows if output_format == 'json' else [
            {'EXEC': row['exec_name'], 'PACKAGE': row['package_id']} for row in rows
        ]
        return render_structured_result(
            StructuredCommandResult(
                status=1,
                data=display_rows,
                shape='table',
            ),
            output_format=output_format,
        )

    def _format_info(self, exec_name: str, output_format: str = 'json'):
        target = self._resolve_exec_target(exec_name)
        payload = self._build_client_payload(target, raw_args='')
        install = payload.get('install') or {}
        package_payload = payload.get('package') or {}
        package_id = payload.get('package_id') or target.get('package_id') or ''
        package_key = payload.get('package_key') or target.get('package_key') or ''
        status_map = self._load_cli_install_status_map([target])
        install_status = self._install_status_text(status_map.get((package_id, package_key)))

        return render_structured_result(
            StructuredCommandResult(
                status=1,
                data={
                    'exec_name': target.get('exec_name') or exec_name,
                    'package_id': package_id,
                    'display_name': target.get('display_name') or '',
                    'description': target.get('description') or '',
                    'package_key': package_key,
                    'executable': package_payload.get('executable_rel_path') or '',
                    'install_status': install_status,
                    'install_dir': install.get('install_dir') or '',
                    'usage': f'xt exec {target.get("exec_name") or exec_name} <raw args>',
                },
                shape='dict',
                width=20,
            ),
            output_format=output_format,
        )

    def _which(self, exec_name: str):
        target = self._resolve_exec_target(exec_name)
        payload = self._build_client_payload(target, raw_args='')
        command = f'external_tool_which {encode_structured_arg(payload)}'
        for item in self._iter_nested_command(command):
            yield item

    def _run_exec(self, exec_name: str, raw_args: str):
        target = self._resolve_exec_target(exec_name)
        payload = self._build_client_payload(target, raw_args=raw_args)
        history = self._history()
        if history is not None:
            history.prepare_xt_run(self.conn, self.history_entry_id_provider(), target)
        command = f'external_tool_exec {encode_structured_arg(payload)}'
        for item in self._iter_nested_command(command):
            yield item

    def _nested_json(self, command: str, payload: dict) -> dict:
        status, text = self._collect_nested_command_text(f'{command} {encode_structured_arg(payload)}')
        if not status:
            raise RuntimeError(text or f'{command} failed')
        try:
            result = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise RuntimeError(f'{command} returned invalid JSON: {text[:300]}') from exc
        if not isinstance(result, dict):
            raise RuntimeError(f'{command} returned invalid response')
        return result

    @staticmethod
    def _render_rows(rows: list[dict], output_format: str = 'table'):
        return render_structured_result(StructuredCommandResult(status=1, data=rows, shape='table'), output_format=output_format)

    @staticmethod
    def _tokens(text: str) -> list[str]:
        try:
            return shlex.split(str(text or ''))
        except ValueError as exc:
            raise ValueError(f'Invalid xt arguments: {exc}') from exc

    def _installed_packages(self, packages: list[dict]) -> dict[tuple[str, str], dict]:
        builder = self._runtime_service().payload_builder
        payloads, keys = [], []
        for package in packages:
            package_id = str(package.get('id') or '')
            try:
                payload = builder.build_client_install_payload(package, platform_alias=self._client_platform(), arch=self._client_arch())
                key = (package_id, str(payload.get('package_key') or ''))
                payloads.append(payload)
            except ValueError as exc:
                key = (package_id, '')
                payloads.append({'error': str(exc), 'package_id': package_id})
            keys.append(key)
        if not payloads:
            return {}
        result = self._nested_json('external_tool_install_statuses', {'tools': payloads})
        items = result.get('items') or []
        return {key: items[idx] if idx < len(items) and isinstance(items[idx], dict) else {}
                for idx, key in enumerate(keys)}

    def _package_list(self, args: str):
        tokens = self._tokens(args)
        if any(token not in ('--json', '--installed', '-i') for token in tokens) or len(tokens) != len(set(tokens)):
            raise ValueError('Usage: xt package list [--installed|-i] [--json]')
        packages = [p for p in self._catalog_service().list_packages() if not p.get('error')
                    and self._catalog_service()._platform_matches(p, self._client_platform())
                    and self._catalog_service()._arch_matches(p, self._client_arch())]
        statuses = self._installed_packages(packages)
        only_installed = '--installed' in tokens or '-i' in tokens
        rows = []
        for package in packages:
            package_id = str(package.get('id') or '')
            key = self._catalog_service().select_package_key(package, self._client_platform(), self._client_arch())
            installed = is_installed_status(self._install_status_text(statuses.get((package_id, key))))
            if only_installed and not installed:
                continue
            rows.append({'package_id': package_id, 'display_name': package.get('display_name') or package_id,
                         'installed': installed})
        rows.sort(key=lambda row: row['package_id'])
        return self._render_rows(rows if '--json' in tokens else [
            {'PACKAGE': row['package_id'], 'NAME': row['display_name'], 'INSTALLED': 'yes' if row['installed'] else 'no'} for row in rows
        ], 'json' if '--json' in tokens else 'table')

    def _publish_xt_lifecycle(self, group: str, operation: str, target: str, state: str, *,
                              result: dict | None = None, error: str = ''):
        """Use the existing Web Manager lifecycle bus/projector and notification preferences."""
        client_id = str(getattr(getattr(self.conn, 'session_info', None), 'client_id', '') or '').strip()
        if not client_id:
            return
        kwargs = {'client_id': client_id, 'operation': operation, 'state': state,
                  'result': result, 'error': error}
        try:
            lifecycle = getattr(self._runtime_service(), 'client_lifecycle_runtime', None)
            if lifecycle is None:
                return
            if group == 'package':
                kwargs.update(action=operation, package=self._catalog_service().get_package(target))
            else:
                kwargs.update(action='daemon', meta=self._instance_meta(target.split('/', 1)[0]),
                              instance_id=target.split('/', 1)[1])
            lifecycle._publish_lifecycle(**kwargs)
        except Exception:
            # Notification failure must never hide the original command result.
            logging.getLogger(__name__).exception('Failed to publish xt lifecycle event')

    def _package_action(self, operation: str, args: str):
        names = self._tokens(args)
        if len(names) != 1:
            raise ValueError(f'Usage: xt package {operation} <package-id>')
        package = self._catalog_service().get_package(names[0])
        payload = self._runtime_service().payload_builder.build_client_install_payload(package,
                       platform_alias=self._client_platform(), arch=self._client_arch())
        before = self._nested_json('external_tool_install_status', payload)
        status = self._install_status_text(before)
        if status in ('unknown', 'error'):
            raise RuntimeError(f'Cannot verify installation status for {names[0]}: {before.get("error") or status}')
        installed = is_installed_status(status)
        if operation == 'install' and installed:
            raise ValueError(f'Package {names[0]} is already installed; no installation performed')
        if operation == 'uninstall' and status == 'not_installed':
            raise ValueError(f'Package {names[0]} is not installed; nothing to uninstall')
        try:
            result = self._nested_json('external_tool_install' if operation == 'install' else 'external_tool_uninstall', payload)
            if result.get('installed') is not (operation == 'install'):
                raise RuntimeError(result.get('message') or f'Package {operation} failed')
        except Exception as exc:
            self._publish_xt_lifecycle('package', operation, names[0], 'failed', error=str(exc))
            raise
        # A concurrent change can turn the dispatched request into a no-op;
        # it is a CLI state conflict, not a failed installation operation.
        if operation == 'install' and result.get('already_installed'):
            raise ValueError(f'Package {names[0]} was already installed; no installation performed')
        if operation == 'uninstall' and result.get('removed') is False:
            raise ValueError(f'Package {names[0]} was not installed; nothing removed')
        return 1, str(result.get('message') or f'Package {names[0]} {operation} completed')

    def _module_list(self, args: str):
        tokens = self._tokens(args)
        if len(tokens) not in (1, 2) or (len(tokens) == 2 and tokens[-1] != '--json'):
            raise ValueError('Usage: xt module list <package-id> [--json]')
        package = self._catalog_service().get_package(tokens[0])
        package_key = self._catalog_service().select_package_key(package, self._client_platform(), self._client_arch())
        rows = []
        for module in package.get('modules') or []:
            try:
                self._catalog_service().resolve_binary_rel_path(package, module.get('binary') or '', package_key)
            except ValueError:
                continue
            rows.append({'module_id': f'{package["id"]}.{module["id"]}',
                         'execution': module.get('execution') or '', 'binary': module.get('binary') or ''})
        return self._render_rows(rows if '--json' in tokens else [
            {'MODULE': row['module_id'], 'EXECUTION': row['execution'], 'BINARY': row['binary']} for row in rows
        ], 'json' if '--json' in tokens else 'table')

    def _instance_meta(self, tool_id: str) -> dict:
        meta = self._catalog_service().get_tool(tool_id)
        if str(meta.get('execution') or '') != 'daemon':
            raise ValueError(f'Instance commands require a daemon module: {tool_id}')
        return meta

    @staticmethod
    def _instance_id(value: str) -> str:
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}', str(value or '')) or value in ('.', '..'):
            raise ValueError('Instance ID must be 1-96 characters: letters, digits, _, . or -; start with letter, digit or _')
        return value

    def _instance_action_payload(self, meta: dict, instance_id: str, action: str = 'status') -> dict:
        return self._runtime_service().payload_builder.build_client_action_payload(meta, action,
                   instance_id=self._instance_id(instance_id))

    def _instance_read(self, meta: dict, instance_id: str) -> dict:
        payload = self._instance_action_payload(meta, instance_id)
        return self._nested_json('external_tool_instance_read', payload)

    def _instance_create(self, args: str):
        tokens = self._tokens(args)
        if not tokens:
            raise ValueError('Usage: xt instance create <package.module> --id <instance-id> [--preset <name>] [--params <JSON>] [--start]')
        meta = self._instance_meta(tokens[0])
        options = {}; index = 1
        while index < len(tokens):
            key = tokens[index]
            if key not in ('--id', '--preset', '--params', '--start') or key in options:
                raise ValueError(f'Invalid or repeated create option: {key}')
            if key == '--start':
                options[key] = True
            else:
                index += 1
                if index >= len(tokens):
                    raise ValueError(f'Missing value for {key}')
                options[key] = tokens[index]
            index += 1
        instance_id = self._instance_id(options.get('--id') or '')
        params = {}
        if '--preset' in options:
            web = self.server.web_service.assembly
            presets = web.external_tool_param_preset_store.list_presets(meta['tool_id'])
            matches = [p for p in presets if p.get('name') == options['--preset'] or p.get('preset_id') == options['--preset']]
            if len(matches) != 1:
                raise FileNotFoundError(f'Preset not found: {options["--preset"]}')
            params.update(matches[0]['params'])
        if '--params' in options:
            try:
                overrides = json.loads(options['--params'])
            except ValueError as exc:
                raise ValueError(f'Invalid --params JSON: {exc}') from exc
            if not isinstance(overrides, dict):
                raise ValueError('--params must be a JSON object')
            params.update(overrides)
        # A module with an instance_name parameter should normally match the CLI identity.
        if 'instance_name' not in params and any(p.get('name') == 'instance_name' for p in meta.get('params') or []):
            params['instance_name'] = instance_id
        builder = self._runtime_service().payload_builder
        start_payload = builder.build_client_start_payload(meta, params=params, instance_id=instance_id,
                  platform_alias=self._client_platform(), arch=self._client_arch())
        target = f'{meta["tool_id"]}/{instance_id}'
        if any(row['module_id'] == meta['tool_id'] and row['instance_id'] == instance_id
               for row in self._load_instance_rows([meta])):
            raise ValueError(
                f'Instance "{instance_id}" already exists for {meta["tool_id"]}. '
                f'Use "xt instance start {instance_id}" to start it, or choose a different --id.'
            )
        try:
            created = self._nested_json('external_tool_instance_create', start_payload)
        except Exception as exc:
            self._publish_xt_lifecycle('instance', 'create', target, 'error', error=str(exc))
            raise
        # Creation is durable even if the optional start fails afterwards.
        self._publish_xt_lifecycle('instance', 'create', target, 'created')
        if options.get('--start'):
            try:
                started = self._nested_json('external_tool_start', start_payload)
                if started.get('running') is not True or 'already running' in str(started.get('message') or '').lower():
                    raise RuntimeError('Instance created, but start failed: ' + str(started.get('message') or 'unknown error'))
                confirmed = self._nested_json('external_tool_status', self._instance_action_payload(meta, instance_id))
                if confirmed.get('running') is not True:
                    raise RuntimeError('Instance created, but exited immediately after start; see instance logs')
            except Exception as exc:
                self._publish_xt_lifecycle('instance', 'start', target, 'error', error=str(exc))
                raise
            return 1, f'Created and started {meta["tool_id"]}/{instance_id} (pid {started.get("pid")})'
        return 1, f'Created {meta["tool_id"]}/{instance_id}'

    def _instance_list(self, args: str):
        tokens = self._tokens(args)
        if len(tokens) > 2 or (len(tokens) == 2 and tokens[-1] != '--json'):
            raise ValueError('Usage: xt instance list [<package-id>|<package.module>] [--json]')
        if tokens == ['--json']:
            tokens = ['', '--json']
        target = tokens[0] if tokens else ''
        json_output = '--json' in tokens
        metas = [m for m in self._catalog_service().list_tools() if str(m.get('execution') or '') == 'daemon'
                 and (not target or m.get('package_id') == target or m.get('tool_id') == target)]
        if target and not metas:
            if '.' in target:
                self._instance_meta(target)  # distinguish an unknown module from a non-daemon one
            else:
                self._catalog_service().get_package(target)
        if not metas:
            return self._render_rows([], 'json' if json_output else 'table')
        rows = self._load_instance_rows(metas)
        return self._render_rows(rows if json_output else [
            {'MODULE': r['module_id'], 'INSTANCE': r['instance_id'], 'STATUS': r['status'], 'PID': r['pid']} for r in rows
        ], 'json' if json_output else 'table')

    def _load_instance_rows(self, metas: list[dict]) -> list[dict]:
        if not metas:
            return []
        payload = {'tools': [{'tool_id': m['tool_id'], 'package_id': m['package_id'], 'module_id': m['id'],
                             'display_name': m.get('display_name') or m['tool_id']} for m in metas]}
        result = self._nested_json('external_tool_list_instances_all', payload)
        rows = [{'module_id': item.get('tool_id') or '', 'instance_id': item.get('instance_id') or '',
                 'status': item.get('status') or '', 'pid': item.get('pid') or ''} for item in result.get('items') or []]
        rows.sort(key=lambda row: (row['module_id'], row['instance_id']))
        return rows

    def _resolve_instance_target(self, tokens: list[str]) -> tuple[dict, str]:
        if len(tokens) == 2:
            return self._instance_meta(tokens[0]), self._instance_id(tokens[1])
        instance_id = self._instance_id(tokens[0])
        metas = [m for m in self._catalog_service().list_tools()
                 if str(m.get('execution') or '') == 'daemon']
        matches = sorted({row['module_id'] for row in self._load_instance_rows(metas)
                          if row['instance_id'] == instance_id})
        if not matches:
            raise FileNotFoundError(f'Instance not found on selected Client: {instance_id}')
        if len(matches) > 1:
            choices = ', '.join(f'{module} {instance_id}' for module in matches)
            raise ValueError(f'Ambiguous instance ID "{instance_id}"; specify <package.module> <instance-id>: {choices}')
        return self._instance_meta(matches[0]), instance_id

    def _follow_instance_logs(self, payload: dict):
        """Follow Client log snapshots using the Server foreground cancellation flag.

        A snapshot is a bounded Client RPC, not the lifetime of the Follow task.
        Clear its command binding before waiting for the next snapshot so a user
        cancelling the Server-side follow does not cancel a finished Client RPC.
        """
        cursor = ''
        while True:
            if (self.conn.get_foreground_task() or {}).get('cancel_requested'):
                yield 0, 'command cancelled'
                return
            try:
                data = self._nested_json('external_tool_instance_logs', {
                    **payload, 'cursor': cursor, 'max_bytes': 65536,
                })
            except Exception:
                if (self.conn.get_foreground_task() or {}).get('cancel_requested'):
                    yield 0, 'command cancelled'
                    return
                raise
            finally:
                # Only this short snapshot's command ID is cleared, not the
                # foreground task. The Server Follow still owns the task slot.
                self.conn.runtime.bind_foreground_command_id(None)
            if (self.conn.get_foreground_task() or {}).get('cancel_requested'):
                yield 0, 'command cancelled'
                return
            if data.get('reset'):
                yield 1, '[Log rotated]'
            content = str(data.get('content') or '')
            if content:
                yield 1, content
            if not data.get('running'):
                if not content:
                    yield 1, '[Log stream ended]'
                return
            cursor = str(data.get('cursor') or '')
            for _ in range(5):
                if (self.conn.get_foreground_task() or {}).get('cancel_requested'):
                    yield 0, 'command cancelled'
                    return
                time.sleep(0.2)

    def _instance_operation(self, operation: str, args: str):
        tokens = self._tokens(args)
        json_output = operation == 'status' and tokens[-1:] == ['--json']
        if json_output:
            tokens.pop()
        follow = operation == 'logs' and any(t in ('--follow', '-f') for t in tokens)
        if follow:
            if sum(t in ('--follow', '-f') for t in tokens) != 1:
                raise ValueError('Specify --follow only once')
            tokens = [t for t in tokens if t not in ('--follow', '-f')]
        if len(tokens) not in (1, 2):
            raise ValueError(f'Usage: xt instance {operation} [<package.module>] <instance-id>' +
                             (' [--json]' if operation == 'status' else ' [--follow|-f]' if operation == 'logs' else ''))
        meta, instance_id = self._resolve_instance_target(tokens)
        if not (operation == 'logs' and follow):
            definition = self._instance_read(meta, instance_id)
        payload = self._instance_action_payload(meta, instance_id, operation)
        if operation in ('start', 'stop', 'restart'):
            before = self._nested_json('external_tool_status', payload)
            running = before.get('running') is True
            if operation == 'start' and running:
                raise ValueError(f'Instance {meta["tool_id"]}/{instance_id} is already running')
            if operation in ('stop', 'restart') and not running:
                raise ValueError(f'Instance {meta["tool_id"]}/{instance_id} is already stopped')
        if operation in ('start', 'stop', 'restart'):
            dispatched = False
            try:
                if operation in ('start', 'restart'):
                    if operation == 'restart':
                        dispatched = True
                        stopped = self._nested_json('external_tool_stop', payload)
                        if isinstance(stopped.get('stop_result'), dict) and stopped['stop_result'].get('already_stopped'):
                            dispatched = False
                            raise ValueError('Instance was already stopped; restart did not occur')
                        if stopped.get('running') or not isinstance(stopped.get('stop_result'), dict):
                            raise RuntimeError('Restart aborted: process was not stopped by this operation')
                    start_payload = self._runtime_service().payload_builder.build_client_start_payload(meta,
                              params=definition['params'], instance_id=instance_id,
                              platform_alias=self._client_platform(), arch=self._client_arch())
                    dispatched = True
                    result = self._nested_json('external_tool_start', start_payload)
                    if 'already running' in str(result.get('message') or '').lower():
                        dispatched = False
                        raise ValueError('Instance was already running; start did not occur')
                    if result.get('running') is not True:
                        raise RuntimeError(result.get('message') or 'Instance did not start')
                    confirmed = self._nested_json('external_tool_status', payload)
                    if confirmed.get('running') is not True:
                        raise RuntimeError('Instance exited immediately after start; see instance logs')
                    yield 1, f'{"Restarted" if operation == "restart" else "Started"} {meta["tool_id"]}/{instance_id} (pid {result.get("pid")})'
                if operation == 'stop':
                    dispatched = True
                    result = self._nested_json('external_tool_stop', payload)
                    if isinstance(result.get('stop_result'), dict) and result['stop_result'].get('already_stopped'):
                        dispatched = False
                        raise ValueError('Instance was already stopped; stop did not occur')
                    if result.get('running') or not isinstance(result.get('stop_result'), dict):
                        raise RuntimeError('Instance is still running; stop failed')
                    yield 1, f'Stopped {meta["tool_id"]}/{instance_id}'
            except Exception as exc:
                if dispatched:
                    self._publish_xt_lifecycle('instance', operation,
                        f'{meta["tool_id"]}/{instance_id}', 'error', error=str(exc))
                raise
        if operation == 'status':
            result = self._nested_json('external_tool_status', payload)
            summary = {
                'module_id': meta['tool_id'], 'instance_id': instance_id, 'status': result.get('status'),
                'running': result.get('running'), 'pid': result.get('pid') or '',
                'started_at': result.get('started_at') or '', 'stopped_at': result.get('stopped_at') or '',
            }
            yield render_structured_result(StructuredCommandResult(status=1, data=summary,
                                          shape='dict', width=16), output_format='json' if json_output else 'table')
        if operation == 'logs':
            if follow:
                yield from self._follow_instance_logs(payload)
                return
            data = self._nested_json('external_tool_instance_logs', {**payload, 'max_bytes': 65536})
            if data.get('reset'):
                yield 1, '[Log rotated]'
            yield 1, str(data.get('content') or '') or 'No log output.'
        return f'{meta["tool_id"]}/{instance_id}'

    def _management(self, group: str, args: str):
        action, remainder = self._split_first_token(args)
        if group == 'package':
            if action == 'list':
                self._suppress_query_history()
                yield self._package_list(remainder)
                return
            if action in ('install', 'uninstall'):
                target, _ = self._split_first_token(remainder)
                outcome = self._package_action(action, remainder)
                self._publish_xt_lifecycle('package', action, target, 'completed', result={'message': outcome[1]})
                yield outcome
                return
        elif group == 'module' and action == 'list':
            self._suppress_query_history()
            yield self._module_list(remainder)
            return
        elif group == 'instance':
            if action == 'list':
                self._suppress_query_history()
                yield self._instance_list(remainder)
                return
            if action == 'create' or action in ('start', 'stop', 'restart', 'status', 'logs'):
                if action in ('status', 'logs'):
                    self._suppress_query_history()
                tokens = self._tokens(remainder)
                if action == 'create':
                    module_id = tokens[0] if tokens else ''
                    idx = tokens.index('--id') if '--id' in tokens else -1
                    instance_id = tokens[idx + 1] if idx >= 0 and idx + 1 < len(tokens) else ''
                    target = f'{module_id}/{instance_id}' if module_id and instance_id else ''
                    yield self._instance_create(remainder)
                else:
                    target = yield from self._instance_operation(action, remainder)
                if target and action in ('create', 'start', 'stop', 'restart'):
                    state = ('created' if action == 'create' and '--start' not in tokens else
                             'stopped' if action == 'stop' else 'started')
                    if action != 'create' or '--start' in tokens:
                        self._publish_xt_lifecycle('instance', action, target, state)
                return
        raise ValueError(f'Unsupported xt {group} action: {action or "(none)"}')

    def xt(self, arg=''):
        usage = ('Usage: xt package list|install|uninstall ... | xt module list <package-id> | '
                 'xt instance create|list|start|stop|restart|status|logs ... | '
                 'xt exec list|info|which|<exec-name> ...')
        subcommand, rest = self._split_first_token(arg)
        if subcommand in ('', 'help', '-h', '--help'):
            self._suppress_query_history()
            yield 1, usage
            return
        if subcommand in ('package', 'module', 'instance'):
            yield from self._management(subcommand, rest)
            return
        if subcommand != 'exec':
            raise ValueError(usage)

        exec_name, raw_args = self._split_first_token(rest)
        if exec_name in ('', 'help', '-h', '--help'):
            self._suppress_query_history()
            yield 1, usage
            return
        if exec_name == 'list':
            if raw_args not in ('', '--json'):
                raise ValueError('Usage: xt exec list [--json]')
            self._suppress_query_history()
            yield self._render_cli_list('json' if raw_args == '--json' else 'table')
            return
        if exec_name == 'info':
            name, info_args = self._split_first_token(raw_args)
            if not name or info_args not in ('', '--json'):
                raise ValueError('Usage: xt exec info <name> [--json]')
            self._suppress_query_history()
            yield self._format_info(name, 'json' if info_args == '--json' else 'table')
            return
        if exec_name == 'which':
            name, other = self._split_first_token(raw_args)
            if not name or other:
                raise ValueError('Usage: xt exec which <name>')
            self._suppress_query_history()
            for item in self._which(name):
                yield item
            return

        # The native argument tail is never interpreted as a Server option.
        for item in self._run_exec(exec_name, raw_args):
            yield item
