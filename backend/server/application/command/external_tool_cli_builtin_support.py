"""Server-side External Tool CLI: package, module, instance and public exec."""

import logging
import re
import time

from core.external_tools.install_status import is_installed_status, normalize_install_status
from core.protocol.control import ControlDomain, ExternalToolAction as A
from core.external_tools.payload import client_control_request
from server.application.command.command_types import COMMAND_TYPE_CONTROL
from core.utils.command_output import (StructuredCommandResult, ResultDataShape,
                                       resolve_presentation, render_presented_result)
from core.protocol.result_envelope import ResultEvent


def _render_structured(result, *, output_format):
    event = result.as_event(requested='json' if output_format == 'json' else None)
    return ResultEvent(event, render_presented_result(event))


class ExternalToolCliBuiltinSupport:
    """
    xt 轻量 CLI 门面。

    约束：
    - Exec 只解析 package.execs 暴露的原生命令，原生 argv 不被改写。
    - Package / Instance 复用既有 Client 操作并根据真实状态确认转移。
    - 状态变化通过现有 External Tool lifecycle / Notification 管线广播。
    """

    def __init__(self, server, conn, command_processor_factory, history_entry_id_provider, catalog_service, runtime_service, param_preset_store):
        self.server = server
        self.conn = conn
        self.command_processor_factory = command_processor_factory
        self.history_entry_id_provider = history_entry_id_provider
        self.catalog_service = catalog_service
        self.runtime_service = runtime_service
        self.param_preset_store = param_preset_store

    def _client_platform(self) -> str:
        info = getattr(self.conn, 'session_info', None)
        value = getattr(info, 'os_alias', '') if info is not None else ''
        normalized = self.catalog_service._normalize_platform(value or '')
        if not normalized:
            raise ValueError('client platform is required for external tool command resolution')
        return normalized

    def _client_arch(self) -> str:
        info = getattr(self.conn, 'session_info', None)
        value = getattr(info, 'arch', '') if info is not None else ''
        normalized = self.catalog_service._normalize_arch(value or '')
        if not normalized:
            raise ValueError('client arch is required for external tool command resolution')
        return normalized

    def _client_cwd(self) -> str:
        info = getattr(self.conn, 'session_info', None)
        return str(getattr(info, 'cwd', '') if info is not None else '').strip()

    def _split_first_token(self, text: str) -> tuple[str, str]:
        raw = str(text or '').lstrip()
        if not raw:
            return '', ''
        match = re.match(r'^(\S+)(?:\s(.*))?$', raw, re.DOTALL)
        return match.group(1), (match.group(2) or '')

    def _strip_raw_arg_separator(self, text: str) -> str:
        raw = str(text or '').strip()
        if raw == '--':
            return ''
        if raw.startswith('-- '):
            return raw[3:].strip()
        return raw

    def _resolve_exec_target(self, exec_name: str) -> dict:
        return self.catalog_service.resolve_exec_target(
            exec_name,
            platform_alias=self._client_platform(),
            arch=self._client_arch(),
        )

    def _build_client_payload(self, target: dict, raw_args: str = '') -> dict:
        runtime_service = self.runtime_service
        payload = runtime_service.payload_builder.build_client_exec_payload(
            target,
            raw_args=self._strip_raw_arg_separator(raw_args),
            platform_alias=self._client_platform(),
            arch=self._client_arch(),
            cwd=self._client_cwd(),
        )
        return payload

    def _control_events(self, action, payload: dict):
        remote = self.runtime_service.remote_execution_service
        if remote is None:
            raise RuntimeError('External Tool Control transport unavailable')
        # XT executes on the Server; only a dispatched Client Control commits
        # the prepared Activity. Preserve the CLI entry ID so the first
        # mutating Control uses the original command instead of a duplicate row.
        # stream_command does not acquire a second foreground execution slot.
        return remote.stream_command(
            self.conn, '', command_type=COMMAND_TYPE_CONTROL,
            domain=ControlDomain.EXTERNAL_TOOL, action=action,
            payload=client_control_request(action, payload),
            history_entry_id=self.history_entry_id_provider(),
            link_foreground_cancel=(action == A.READ_INSTANCE_LOGS),
        )

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

        try:
            decoded = self._nested_json(A.GET_INSTALL_STATUSES, {'tools': payloads})
            status_items = decoded.get('items')
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
        catalog = self.catalog_service
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

    def _render_cli_list(self, args: dict):
        rows = self._build_cli_list_payload()
        output, layout = resolve_presentation(args, ResultDataShape.LINES)
        if not rows and output != 'json':
            return ResultEvent.completed(message='No installed external tool Exec commands for this Client.')
        result = StructuredCommandResult(status=1, data=rows, shape=layout,
                                         line_field='exec_name',
                                         columns=(('exec_name', 'EXEC'), ('package_id', 'PACKAGE')))
        return _render_structured(result, output_format=output)

    def _format_info(self, exec_name: str, args: dict):
        target = self._resolve_exec_target(exec_name)
        payload = self._build_client_payload(target, raw_args='')
        install = payload.get('install') or {}
        package_payload = payload.get('package') or {}
        package_id = payload.get('package_id') or target.get('package_id') or ''
        package_key = payload.get('package_key') or target.get('package_key') or ''
        status_map = self._load_cli_install_status_map([target])
        install_status = self._install_status_text(status_map.get((package_id, package_key)))

        output, layout = resolve_presentation(args, ResultDataShape.FLAT)
        return _render_structured(
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
                shape=layout,
                width=20,
            ),
            output_format=output,
        )

    def _which(self, exec_name: str):
        target = self._resolve_exec_target(exec_name)
        payload = self._build_client_payload(target, raw_args='')
        result = self._nested_json(A.GET_INSTALL_STATUSES, {'tools': [payload]})
        items = result.get('items') or []
        item = items[0] if len(items) == 1 and isinstance(items[0], dict) else {}
        path = str(item.get('executable_path') or '')
        if item.get('error') or not item.get('installed') or not path:
            raise FileNotFoundError(str(item.get('error') or item.get('message') or 'External tool executable is not installed'))
        yield ResultEvent.completed(message=path)

    def _run_exec(self, exec_name: str, raw_args: str):
        target = self._resolve_exec_target(exec_name)
        payload = self._build_client_payload(target, raw_args=raw_args)
        for item in self._control_events(A.EXEC, payload):
            if item.phase == 'started':
                continue
            if item.terminal_status is not None and not item.succeeded and not item.visible_text():
                yield item.with_text('External Tool execution failed')
            else:
                yield item

    def _nested_result(self, action, payload: dict):
        remote = self.runtime_service.remote_execution_service
        collected = remote.command_stream_service.collect_envelope(self._control_events(action, payload))
        if collected.status not in ('success', 'partial'):
            raise RuntimeError(collected.text or f'External Tool {action} failed')
        return collected

    def _nested_json(self, action, payload: dict) -> dict:
        collected = self._nested_result(action, payload)
        if not isinstance(collected.data, dict):
            raise RuntimeError(f'External Tool {action} returned invalid structured data')
        return collected.data

    def _nested_message(self, action, payload: dict) -> str:
        return self._nested_result(action, payload).text

    def _instance_status(self, payload: dict) -> dict:
        tool_id = str(payload.get('tool_id') or '')
        instance_id = str(payload.get('instance_id') or '')
        result = self._nested_json(A.LIST_INSTANCES, {'tools': [{
            'tool_id': tool_id, 'package_id': payload.get('package_id') or '',
            'module_id': payload.get('module_id') or '', 'instance_ids': [instance_id],
        }]})
        items = result.get('items') or []
        if len(items) != 1 or not isinstance(items[0], dict):
            raise FileNotFoundError(f'Instance not found: {tool_id}/{instance_id}')
        return items[0]

    @staticmethod
    def _render_rows(rows: list[dict], args: dict, *, line_field,
                     columns=(), line_separator='/', text_values=None):
        output, layout = resolve_presentation(args, ResultDataShape.LINES)
        result = StructuredCommandResult(status=1, data=rows, shape=layout,
                                         line_field=line_field, columns=columns,
                                         line_separator=line_separator, text_values=text_values)
        return _render_structured(result, output_format=output)

    def _installed_packages(self, packages: list[dict]) -> dict[tuple[str, str], dict]:
        builder = self.runtime_service.payload_builder
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
        result = self._nested_json(A.GET_INSTALL_STATUSES, {'tools': payloads})
        items = result.get('items') or []
        return {key: items[idx] if idx < len(items) and isinstance(items[idx], dict) else {}
                for idx, key in enumerate(keys)}

    def _package_list(self, args: dict):
        packages = [p for p in self.catalog_service.list_packages() if not p.get('error')
                    and self.catalog_service._platform_matches(p, self._client_platform())
                    and self.catalog_service._arch_matches(p, self._client_arch())]
        statuses = self._installed_packages(packages)
        only_installed = args['installed']
        rows = []
        for package in packages:
            package_id = str(package.get('id') or '')
            key = self.catalog_service.select_package_key(package, self._client_platform(), self._client_arch())
            installed = is_installed_status(self._install_status_text(statuses.get((package_id, key))))
            if only_installed and not installed:
                continue
            rows.append({'package_id': package_id, 'display_name': package.get('display_name') or package_id,
                         'installed': installed})
        rows.sort(key=lambda row: row['package_id'])
        return self._render_rows(rows, args, line_field='package_id',
                                 columns=(('package_id', 'PACKAGE'),
                                          ('display_name', 'NAME'), ('installed', 'INSTALLED')),
                                 text_values={'installed': {True: 'yes', False: 'no'}})


    def _publish_xt_lifecycle(self, group: str, operation: str, target: str, state: str, *,
                              result: dict | None = None, error: str = ''):
        """Use the existing Web Manager lifecycle bus/projector and notification preferences."""
        client_id = str(getattr(getattr(self.conn, 'session_info', None), 'client_id', '') or '').strip()
        if not client_id:
            return
        kwargs = {'client_id': client_id, 'operation': operation, 'state': state,
                  'result': result, 'error': error}
        try:
            lifecycle = getattr(self.runtime_service, 'client_lifecycle_runtime', None)
            if lifecycle is None:
                return
            if group == 'package':
                kwargs.update(action=operation, package=self.catalog_service.get_package(target))
            else:
                kwargs.update(action='daemon', meta=self._instance_meta(target.split('/', 1)[0]),
                              instance_id=target.split('/', 1)[1])
            lifecycle._publish_lifecycle(**kwargs)
        except Exception:
            # Notification failure must never hide the original command result.
            logging.getLogger(__name__).exception('Failed to publish xt lifecycle event')

    def _package_action(self, operation: str, args: dict):
        package_id = args['package']
        package = self.catalog_service.get_package(package_id)
        payload = self.runtime_service.payload_builder.build_client_install_payload(package,
                       platform_alias=self._client_platform(), arch=self._client_arch())
        before = self._nested_json(A.GET_INSTALL_STATUSES, {'tools': [payload]})['items'][0]
        status = self._install_status_text(before)
        if status in ('unknown', 'error'):
            raise RuntimeError(f'Cannot verify installation status for {package_id}: {before.get("error") or status}')
        installed = is_installed_status(status)
        if operation == 'install' and installed:
            raise ValueError(f'Package {package_id} is already installed; no installation performed')
        if operation == 'uninstall' and status == 'not_installed':
            raise ValueError(f'Package {package_id} is not installed; nothing to uninstall')
        try:
            message = self._nested_message(A.INSTALL_PACKAGE if operation == 'install' else A.UNINSTALL_PACKAGE, payload)
        except Exception as exc:
            self._publish_xt_lifecycle('package', operation, package_id, 'failed', error=str(exc))
            raise
        return ResultEvent.completed(message=message or f'Package {package_id} {operation} completed')

    def _module_list(self, args: dict):
        package = self.catalog_service.get_package(args['package'])
        package_key = self.catalog_service.select_package_key(package, self._client_platform(), self._client_arch())
        rows = []
        for module in package.get('modules') or []:
            try:
                self.catalog_service.resolve_binary_rel_path(package, module.get('binary') or '', package_key)
            except ValueError:
                continue
            rows.append({'module_id': f'{package["id"]}.{module["id"]}',
                         'execution': module.get('execution') or '', 'binary': module.get('binary') or ''})
        return self._render_rows(rows, args, line_field='module_id',
                                 columns=(('module_id', 'MODULE'),
                                          ('execution', 'EXECUTION'), ('binary', 'BINARY')))


    def _instance_meta(self, tool_id: str) -> dict:
        meta = self.catalog_service.get_tool(tool_id)
        if str(meta.get('execution') or '') != 'daemon':
            raise ValueError(f'Instance commands require a daemon module: {tool_id}')
        return meta

    @staticmethod
    def _instance_id(value: str) -> str:
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}', str(value or '')) or value in ('.', '..'):
            raise ValueError('Instance ID must be 1-96 characters: letters, digits, _, . or -; start with letter, digit or _')
        return value

    def _instance_action_payload(self, meta: dict, instance_id: str, action: str = 'status') -> dict:
        return self.runtime_service.payload_builder.build_client_action_payload(meta, action,
                   instance_id=self._instance_id(instance_id))

    def _instance_read(self, meta: dict, instance_id: str) -> dict:
        payload = self._instance_action_payload(meta, instance_id)
        return self._nested_json(A.READ_INSTANCE, payload)

    def _instance_create(self, args: dict):
        meta = self._instance_meta(args['module'])
        instance_id = self._instance_id(args['id'])
        params = {}
        if args['preset']:
            presets = self.param_preset_store.list_presets(meta['tool_id'])
            matches = [p for p in presets if p.get('name') == args['preset'] or p.get('preset_id') == args['preset']]
            if len(matches) != 1:
                raise FileNotFoundError(f'Preset not found: {args["preset"]}')
            params.update(matches[0]['params'])
        # The shared Job/Script grammar owns `-- --key value` and its validation.
        params.update(args['params'])
        # A module with an instance_name parameter should normally match the CLI identity.
        if 'instance_name' not in params and any(p.get('name') == 'instance_name' for p in meta.get('params') or []):
            params['instance_name'] = instance_id
        builder = self.runtime_service.payload_builder
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
            self._nested_message(A.CREATE_INSTANCE, start_payload)
        except Exception as exc:
            self._publish_xt_lifecycle('instance', 'create', target, 'error', error=str(exc))
            raise
        # Creation is durable even if the optional start fails afterwards.
        self._publish_xt_lifecycle('instance', 'create', target, 'created')
        if args['start']:
            try:
                started = self._nested_message(A.START_INSTANCE, start_payload)
                if 'already running' in started.lower():
                    raise RuntimeError('Instance created, but start found an existing running process')
                confirmed = self._instance_status(self._instance_action_payload(meta, instance_id))
                if confirmed.get('running') is not True:
                    raise RuntimeError('Instance created, but exited immediately after start; see instance logs')
            except Exception as exc:
                self._publish_xt_lifecycle('instance', 'start', target, 'error', error=str(exc))
                raise
            self._publish_xt_lifecycle('instance', 'create', target, 'started')
            return ResultEvent.completed(message=f'Created and started {meta["tool_id"]}/{instance_id} (pid {confirmed.get("pid")})')
        return ResultEvent.completed(message=f'Created {meta["tool_id"]}/{instance_id}')

    def _instance_list(self, args: dict):
        target = args['name'] or ''
        metas = [m for m in self.catalog_service.list_tools() if str(m.get('execution') or '') == 'daemon'
                 and (not target or m.get('package_id') == target or m.get('tool_id') == target)]
        if target and not metas:
            if '.' in target:
                self._instance_meta(target)  # distinguish an unknown module from a non-daemon one
            else:
                self.catalog_service.get_package(target)
        if not metas:
            return self._render_rows([], args, line_field=('module_id', 'instance_id'))
        rows = self._load_instance_rows(metas)
        return self._render_rows(rows, args, line_field=('module_id', 'instance_id'),
                                 columns=(('module_id', 'MODULE'), ('instance_id', 'INSTANCE'),
                                          ('status', 'STATUS'), ('pid', 'PID')))


    def _load_instance_rows(self, metas: list[dict]) -> list[dict]:
        if not metas:
            return []
        payload = {'tools': [{'tool_id': m['tool_id'], 'package_id': m['package_id'], 'module_id': m['id'],
                             'display_name': m.get('display_name') or m['tool_id']} for m in metas]}
        result = self._nested_json(A.LIST_INSTANCES, payload)
        rows = [{'module_id': item.get('tool_id') or '', 'instance_id': item.get('instance_id') or '',
                 'status': item.get('status') or '', 'pid': item.get('pid') or ''} for item in result.get('items') or []]
        rows.sort(key=lambda row: (row['module_id'], row['instance_id']))
        return rows

    def _resolve_instance_target(self, tokens: list[str]) -> tuple[dict, str]:
        if len(tokens) == 2:
            return self._instance_meta(tokens[0]), self._instance_id(tokens[1])
        instance_id = self._instance_id(tokens[0])
        metas = [m for m in self.catalog_service.list_tools()
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
                yield ResultEvent.completed('cancelled', 'command cancelled')
                return
            try:
                data = self._nested_json(A.READ_INSTANCE_LOGS, {
                    **payload, 'cursor': cursor, 'max_bytes': 65536,
                })
            except Exception:
                if (self.conn.get_foreground_task() or {}).get('cancel_requested'):
                    yield ResultEvent.completed('cancelled', 'command cancelled')
                    return
                raise
            if (self.conn.get_foreground_task() or {}).get('cancel_requested'):
                yield ResultEvent.completed('cancelled', 'command cancelled')
                return
            if data.get('reset'):
                yield ResultEvent.chunk('[Log rotated]')
            content = str(data.get('content') or '')
            if content:
                yield ResultEvent.chunk(content)
            if not data.get('running'):
                yield ResultEvent.completed(message='' if content else '[Log stream ended]')
                return
            cursor = str(data.get('cursor') or '')
            for _ in range(5):
                if (self.conn.get_foreground_task() or {}).get('cancel_requested'):
                    yield ResultEvent.completed('cancelled', 'command cancelled')
                    return
                time.sleep(0.2)

    @staticmethod
    def _instance_target_tokens(args: dict) -> list[str]:
        """One ID or module+ID; --module/--name are equivalent named spellings."""
        first, second, module = args['name'], args['instance'], args['module']
        if module:
            if second or not first:
                raise ValueError('Specify one instance name with --module MODULE')
            return [module, first]
        if not first:
            raise ValueError('Instance name is required (positional or --name)')
        return [first, second] if second else [first]

    def _instance_operation(self, operation: str, args: dict):
        json_output = args.get('json', False)
        follow = args.get('follow', False)
        meta, instance_id = self._resolve_instance_target(self._instance_target_tokens(args))
        definition = None
        if not (operation == 'logs' and follow):
            definition = self._instance_read(meta, instance_id)
        payload = self._instance_action_payload(meta, instance_id, operation)
        if operation in ('start', 'stop', 'restart'):
            before = self._instance_status( payload)
            running = before.get('running') is True
            if operation == 'start' and running:
                raise ValueError(f'Instance {meta["tool_id"]}/{instance_id} is already running')
            if operation in ('stop', 'restart') and not running:
                raise ValueError(f'Instance {meta["tool_id"]}/{instance_id} is already stopped')
        if operation in ('start', 'stop', 'restart'):
            dispatched = False
            try:
                if operation in ('start', 'restart'):
                    start_payload = self.runtime_service.payload_builder.build_client_start_payload(
                        meta, params={**definition['params'], **args.get('params', {})}, instance_id=instance_id,
                        platform_alias=self._client_platform(), arch=self._client_arch())
                    dispatched = True
                    message = self._nested_message(
                        A.RESTART_INSTANCE if operation == 'restart' else A.START_INSTANCE,
                        start_payload)
                    if 'already running' in message.lower():
                        dispatched = False
                        raise ValueError('Instance was already running; start did not occur')
                    confirmed = self._instance_status(payload)
                    if confirmed.get('running') is not True:
                        raise RuntimeError('Instance exited immediately after start; see instance logs')
                    yield ResultEvent.completed(message=f'{"Restarted" if operation == "restart" else "Started"} {meta["tool_id"]}/{instance_id} (pid {confirmed.get("pid")})')
                if operation == 'stop':
                    dispatched = True
                    self._nested_message(A.STOP_INSTANCE, payload)
                    yield ResultEvent.completed(message=f'Stopped {meta["tool_id"]}/{instance_id}')
            except Exception as exc:
                if dispatched:
                    self._publish_xt_lifecycle('instance', operation,
                        f'{meta["tool_id"]}/{instance_id}', 'error', error=str(exc))
                raise
        if operation == 'status':
            result = self._instance_status( payload)
            summary = {
                'module_id': meta['tool_id'], 'instance_id': instance_id, 'status': result.get('status'),
                'running': result.get('running'), 'pid': result.get('pid') or '',
                'started_at': result.get('started_at') or '', 'stopped_at': result.get('stopped_at') or '',
            }
            yield _render_structured(StructuredCommandResult(status=1, data=summary,
                                          shape='dict', width=16), output_format='json' if json_output else 'text')
        if operation == 'logs':
            if follow:
                yield from self._follow_instance_logs(payload)
                return
            data = self._nested_json(A.READ_INSTANCE_LOGS, {**payload, 'max_bytes': 65536})
            if data.get('reset'):
                yield ResultEvent.chunk('[Log rotated]')
            yield ResultEvent.completed(message=str(data.get('content') or '') or 'No log output.')
        return f'{meta["tool_id"]}/{instance_id}'

    def xt(self, invocation):
        """Dispatch one already parsed Registry leaf to its business operation."""
        action = invocation.action
        args = invocation.arguments
        if action in ('help', 'exec.help'):
            from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
            yield ResultEvent.completed(message=SERVER_COMMAND_REGISTRY.help('xt exec' if action == 'exec.help' else 'xt'))
        elif action == 'exec.list':
            yield self._render_cli_list(args)
        elif action == 'exec.info':
            yield self._format_info(args['name'], args)
        elif action == 'exec.which':
            yield from self._which(args['name'])
        elif action == 'exec.run':
            exec_name, raw_args = self._split_first_token(args['command'])
            if not exec_name:
                raise ValueError('External Tool exec name is required')
            yield from self._run_exec(exec_name, raw_args)
        elif action == 'package.list':
            yield self._package_list(args)
        elif action in ('package.install', 'package.uninstall'):
            operation = action.split('.')[1]
            outcome = self._package_action(operation, args)
            self._publish_xt_lifecycle('package', operation, args['package'],
                                       'completed', result={'message': outcome.visible_text()})
            yield outcome
        elif action == 'module.list':
            yield self._module_list(args)
        elif action == 'instance.list':
            yield self._instance_list(args)
        elif action == 'instance.create':
            yield self._instance_create(args)
        elif action in ('instance.start', 'instance.stop', 'instance.restart',
                        'instance.status', 'instance.logs'):
            operation = action.split('.')[1]
            target = yield from self._instance_operation(operation, args)
            if target and operation in ('start', 'stop', 'restart'):
                self._publish_xt_lifecycle('instance', operation, target,
                                           'stopped' if operation == 'stop' else 'started')
        else:
            raise ValueError(f'Unknown registered External Tool action: {action}')
