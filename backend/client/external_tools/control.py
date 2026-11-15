"""External Tool Control execution, backed by existing Client business services."""
import os
from contextlib import ExitStack, contextmanager
from threading import RLock

from client.external_tools.service import ExternalToolClientService
from client.external_tools.launcher import resolve_external_tool_launcher
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from core.protocol.control import ExternalToolAction as A
from core.protocol.result_envelope import ResultEnvelope


class ExternalToolControl:
    def __init__(self, runtime):
        self.runtime = runtime
        self._mutex = RLock()
        self._locks = {}

    @contextmanager
    def _exclusive(self, payload):
        # Instance-local synchronization permits independent stop without racing
        # start, restart or cleanup on the same instance.
        package = str(payload.get('package_id') or '')
        module = str(payload.get('module_id') or '')
        instance = str(payload.get('instance_id') or '')
        keys = [('package', package)]
        if module and instance:
            keys.append(('instance', package, module, instance))
        with self._mutex:
            locks = [self._locks.setdefault(key, RLock()) for key in keys]
        with ExitStack() as stack:
            for lock in locks:
                stack.enter_context(lock)
            yield

    @staticmethod
    def _instance_payload(service, payload):
        # Never use request-provided paths for status, stop, logs or deletion.
        definition = service._instance_definition_path(payload)
        directory = os.path.dirname(definition)
        return {key: value for key, value in payload.items() if key != 'runtime'} | {
            'runtime': {
                'pid_file': os.path.join(directory, 'tool.pid'),
                'state_file': os.path.join(directory, 'state.json'),
                'stdout': os.path.join(directory, 'stdout.log'),
            },
        }

    @staticmethod
    def _check_start_paths(service, payload):
        # The Server renders argv/config; the Client owns writable lifecycle paths.
        directory = os.path.dirname(service._instance_definition_path(payload))
        runtime = payload.get('runtime') or {}
        for key, basename in (('pid_file', 'tool.pid'), ('state_file', 'state.json'), ('stdout', 'stdout.log')):
            actual = service.expand_path(runtime.get(key) or '')
            expected = os.path.join(directory, basename)
            if os.path.normcase(os.path.abspath(actual)) != os.path.normcase(os.path.abspath(expected)):
                raise ValueError(f'Invalid managed runtime.{key} path')

    def _resolve_input_variables(self, payload):
        resolver = self.runtime.command_variable_resolver
        def expand(value):
            if isinstance(value, str):
                return resolver.resolve(value) if '${' in value else value
            if isinstance(value, list):
                return [expand(item) for item in value]
            if isinstance(value, dict):
                return {key: expand(item) for key, item in value.items()}
            return value
        return {key: expand(value) if key in ('params', 'runtime', 'config') else value
                for key, value in payload.items()}

    @staticmethod
    def _install_status_item(row, *, details=False):
        # Bulk catalog/XT status checks need facts, not install logs. The
        # explicit Web detail request is the only consumer of paths/logs/cache.
        item = {key: row[key] for key in (
            'package_id', 'installed', 'install_status', 'executable_path', 'error',
        ) if key in row}
        if details:
            for key in ('package_key', 'install_dir', 'exec_paths', 'commands',
                        'install_log', 'install_log_path'):
                if key in row:
                    item[key] = row[key]
            cache = row.get('cache') or {}
            item['cache'] = {key: cache[key] for key in (
                'exists', 'cache_path', 'cache_dir', 'size', 'mtime',
            ) if key in cache}
        return item

    @staticmethod
    def _instance_status_item(row):
        # The Web Instance Info dialog uses flat runtime paths and argv; the
        # persisted state (including full install/cache data) stays Client-local.
        item = {key: row[key] for key in (
            'tool_id', 'package_id', 'module_id', 'instance_id', 'status',
            'running', 'pid', 'params', 'started_at', 'stopped_at',
            'stdout', 'stderr', 'pid_file', 'state_file', 'argv', 'cwd',
        ) if key in row}
        config = row.get('config') or {}
        if config.get('target'):
            item['config'] = {'target': config['target']}
        if row.get('message'):
            item['message'] = row['message']
        return item

    def execute(self, scope, action, payload):
        try:
            payload = self._resolve_input_variables(payload)
        except Exception as exc:
            return 0, ResultEnvelope(status='error', message=str(exc)).as_payload()
        service = ExternalToolClientService(scope)
        try:
            if action == A.INSTALL_PACKAGE:
                with self._exclusive(payload):
                    data = service.install_payload(payload)
            elif action == A.UNINSTALL_PACKAGE:
                with self._exclusive(payload):
                    data = service.uninstall_payload(payload)
            elif action == A.GET_INSTALL_STATUSES:
                data = service.install_statuses_payload(payload)
                data = {'items': [self._install_status_item(row, details=bool(payload.get('include_details')))
                                  for row in data['items']]}
                items = data['items']
                failures = [item for item in items if item.get('error')]
                if failures:
                    status = 'error' if len(failures) == len(items) else 'partial'
                    return (0 if status == 'error' else 1), ResultEnvelope(
                        status=status, message='Some install status queries failed', data=data,
                    ).as_payload()
            elif action == A.CLEAR_PACKAGE_CACHE:
                with self._exclusive(payload):
                    data = service.clear_cache_payload(payload)
            elif action == A.RESOLVE_LAUNCHER:
                resolved = resolve_external_tool_launcher(payload.get('launcher') or {})
                data = {'executable': resolved['executable']}
            elif action == A.CREATE_INSTANCE:
                with self._exclusive(payload):
                    data = service.create_instance_payload(payload)
            elif action == A.READ_INSTANCE:
                definition = service.read_instance_definition_payload(payload)
                data = {'params': definition['params']}
            elif action == A.READ_INSTANCE_LOGS:
                data = service.instance_log_chunk_payload(self._instance_payload(service, payload))
            elif action == A.START_INSTANCE:
                with self._exclusive(payload):
                    self._check_start_paths(service, payload)
                    data = service.start_payload(payload)
                    if not data.get('running'):
                        raise RuntimeError(data.get('message') or 'Instance did not start')
                    if not service.status_from_payload(self._instance_payload(service, payload)).get('running'):
                        raise RuntimeError('Instance exited immediately after start')
            elif action == A.STOP_INSTANCE:
                with self._exclusive(payload):
                    target = self._instance_payload(service, payload)
                    service.read_instance_definition_payload(target)
                    data = service.stop_payload(target)
                    if data.get('running'):
                        raise RuntimeError('Instance is still running after stop')
                    if (data.get('stop_result') or {}).get('already_stopped'):
                        raise ValueError('Instance was already stopped')
            elif action == A.RESTART_INSTANCE:
                with self._exclusive(payload):
                    self._check_start_paths(service, payload)
                    target = self._instance_payload(service, payload)
                    service.read_instance_definition_payload(target)
                    if not service.status_from_payload(target).get('running'):
                        raise ValueError('Instance is already stopped')
                    stopped = service.stop_payload({**target, 'lifecycle': payload.get('lifecycle') or {}})
                    if stopped.get('running'):
                        raise RuntimeError('Restart aborted: instance did not stop')
                    data = service.start_payload(payload)
                    if not data.get('running'):
                        raise RuntimeError('Restart failed: instance did not start')
                    if not service.status_from_payload(target).get('running'):
                        raise RuntimeError('Restart failed: instance exited immediately')
            elif action == A.LIST_INSTANCES:
                tools = payload.get('tools')
                if not isinstance(tools, list):
                    raise ValueError('list_instances requires tools array')
                data = service.list_instances_all_payload({'tools': tools}) if tools else {'items': []}
                requested = {
                    str(tool.get('tool_id') or ''): set(tool['instance_ids'])
                    for tool in tools if isinstance(tool, dict) and 'instance_ids' in tool
                }
                if requested:
                    existing = {(item.get('tool_id'), item.get('instance_id')) for item in data['items']}
                    for tool_id, instance_ids in requested.items():
                        for instance_id in instance_ids:
                            if (tool_id, instance_id) not in existing:
                                raise FileNotFoundError(f'Instance not found: {tool_id}/{instance_id}')
                    data['items'] = [item for item in data['items'] if
                                     item.get('tool_id') not in requested or item.get('instance_id') in requested[item.get('tool_id')]]
                data = {'items': [self._instance_status_item(row) for row in data['items']]}
            elif action == A.REMOVE_INSTANCE:
                with self._exclusive(payload):
                    target = self._instance_payload(service, payload)
                    service.read_instance_definition_payload(target)
                    data = service.remove_instance_payload(target)
            elif action == A.CLEAR_INSTANCE_LOGS:
                with self._exclusive(payload):
                    target = self._instance_payload(service, payload)
                    service.read_instance_definition_payload(target)
                    data = service.clear_logs_payload(target)
            elif action == A.PREVIEW_INSTANCE:
                preview = service.preview_payload(payload)
                data = {key: preview[key] for key in ('instance_id', 'shell', 'cwd', 'shell_command')
                        if key in preview}
            elif action == A.RUN_ONESHOT:
                outcome = service.oneshot_payload(payload)
                # The result dialog consumes these fields; install/config/runtime
                # details belong to their dedicated read actions.
                data = {key: outcome[key] for key in (
                    'success', 'status', 'returncode',
                    'stdout', 'stderr', 'duration_sec', 'run_id',
                ) if key in outcome}
                if not outcome.get('success'):
                    status = 'timed_out' if outcome.get('timed_out') else 'error'
                    return 0, ResultEnvelope(status=status, message=outcome.get('message') or 'One-shot failed', data=data).as_payload()
            elif action == A.EXEC:
                # The native command runner streams stdout/stderr through the
                # bound command host. Its terminal outcome is returned once here.
                commands = self.runtime.command_executor.get_commands()
                commands.bind_execution(scope.command_id, scope.execution_context)
                code, result = ExternalToolClientService(commands).execute_cli_payload(payload)
                if isinstance(result, dict):
                    return code, ResultEnvelope(status=result['status'], message=result['message']).as_payload()
                return code, ResultEnvelope(status='success' if code else 'error', message=str(result)).as_payload()
            else:
                raise ValueError(f'Unsupported External Tool action: {action}')

            if not isinstance(data, dict):
                raise TypeError(f'Invalid External Tool {action} result')
            # An operational response is not allowed to claim success when the
            # observable business state contradicts it.
            if action == A.INSTALL_PACKAGE and data.get('installed') is not True:
                raise RuntimeError(data.get('message') or 'Package is not installed')
            if action == A.UNINSTALL_PACKAGE and data.get('installed') is not False:
                raise RuntimeError(data.get('message') or 'Package is still installed')
            if action == A.INSTALL_PACKAGE:
                return 1, ResultEnvelope(message='Package installed successfully').as_payload()
            if action == A.UNINSTALL_PACKAGE:
                return 1, ResultEnvelope(message='Package uninstalled').as_payload()
            if action == A.CLEAR_PACKAGE_CACHE:
                message = 'Package cache cleared' if data.get('cache_removed') else 'No cached package found'
                return 1, ResultEnvelope(message=message).as_payload()
            # Mutations have a verified completion, not a serialized state
            # snapshot. Query/preview/log actions return only consumed data.
            if action in (A.CREATE_INSTANCE, A.START_INSTANCE, A.STOP_INSTANCE,
                          A.RESTART_INSTANCE, A.REMOVE_INSTANCE, A.CLEAR_INSTANCE_LOGS):
                if action == A.CREATE_INSTANCE and (data.get('status') != 'created' or data.get('running')):
                    raise RuntimeError('Instance was not created')
                if action == A.REMOVE_INSTANCE and data.get('removed') is not True:
                    raise RuntimeError('Instance was not removed')
                if action == A.CLEAR_INSTANCE_LOGS and data.get('cleared') is not True:
                    raise RuntimeError('Instance logs were not cleared')
                names = {
                    A.CREATE_INSTANCE: 'Instance created', A.START_INSTANCE: 'Instance started',
                    A.STOP_INSTANCE: 'Instance stopped', A.RESTART_INSTANCE: 'Instance restarted',
                    A.REMOVE_INSTANCE: 'Instance removed', A.CLEAR_INSTANCE_LOGS: 'Instance logs cleared',
                }
                message = names[action]
                if action == A.START_INSTANCE and 'already running' in str(data.get('message') or '').lower():
                    message = 'Instance already running'
                return 1, ResultEnvelope(message=message).as_payload()
            message = str(data.get('message') or '') if action == A.RUN_ONESHOT else ''
            return 1, ResultEnvelope(message=message, data=data).as_payload()
        except (CommandCancelledError, CommandTimeoutError):
            raise
        except Exception as exc:
            return 0, ResultEnvelope(status='error', message=str(exc)).as_payload()
