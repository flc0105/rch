"""Server-side `xt exec` command facade for installed client executables."""

import json

from core.external_tools.install_status import is_installed_status, normalize_install_status
from core.protocol.structured_arg_codec import encode_structured_arg
from core.utils.command_output import StructuredCommandResult, render_structured_result


class ExternalToolCliBuiltinSupport:
    """
    xt 轻量 CLI 门面。

    约束：
    - 只解析 package.execs 的原生 exec name
    - 不提供 install；安装仍属于 package/web external tool 管理
    - 执行时只运行已安装 package exec，并把原始参数追加到 argv
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

    def xt(self, arg=''):
        usage = ('Usage: xt exec list [--json] | xt exec info <name> [--json] | '
                 'xt exec which <name> | xt exec <name> [--] <raw args...>')
        subcommand, rest = self._split_first_token(arg)
        if subcommand in ('', 'help', '-h', '--help'):
            self._suppress_query_history()
            yield 1, usage
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
