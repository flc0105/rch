import json

from client.external_tools.launcher import resolve_external_tool_launcher
from client.external_tools.service import ExternalToolClientService
from core.utils.decorator import desc
from client.commands.runtime.interrupts import interruptible


class CommandExternalToolMixin:
    """
    Client-side external tool lifecycle commands.

    Server renders the payload; client performs local operations:
    - check/install package
    - write config
    - start detached process
    - stop/status/list/logs/remove/clear logs
    """

    @property
    def external_tool_service(self) -> ExternalToolClientService:
        service = getattr(self, '_client_external_tool_service', None)
        if service is None:
            service = ExternalToolClientService(self)
            self._client_external_tool_service = service
        return service

    def _decode_external_tool_payload(self, arg):
        payload = self.structured_arg_codec.decode(arg)
        if not isinstance(payload, dict):
            raise ValueError('Invalid external tool payload')
        return payload

    def _json_result(self, payload: dict):
        return 1, json.dumps(payload, ensure_ascii=False, indent=2)

    @desc('Uninstall an external tool package when no instances are running', group='runtime', suggest=False)
    @interruptible()
    def external_tool_uninstall(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
            return self._json_result(self.external_tool_service.uninstall_payload(payload))
        except Exception as e:
            return 0, f'Failed to uninstall external tool: {e}'

    @desc('Resolve the launcher executable for an external tool module', group='runtime', suggest=False)
    @interruptible()
    def external_tool_resolve_launcher(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
            launcher = payload.get('launcher') if isinstance(payload.get('launcher'), dict) else {}
            return self._json_result(resolve_external_tool_launcher(launcher))
        except Exception as e:
            return 0, f'Failed to resolve external tool launcher: {e}'

    @desc('Start an external tool instance', group='runtime', suggest=False)
    @interruptible()
    def external_tool_start(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
            return self._json_result(self.external_tool_service.start_payload(payload))
        except Exception as e:
            return 0, f'Failed to start external tool: {e}'

    @desc('Install and run an external tool package', group='runtime', suggest=False)
    @interruptible()
    def external_tool_run(self, arg=''):
        return self.external_tool_start(arg)

    @desc('Preview the final external tool shell command without starting it', group='runtime', suggest=False)
    @interruptible()
    def external_tool_preview(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
            return self._json_result(self.external_tool_service.preview_payload(payload))
        except Exception as e:
            return 0, f'Failed to preview external tool command: {e}'

    @desc('Run an external tool module once and return captured output', group='runtime', suggest=False)
    @interruptible()
    def external_tool_oneshot(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
            return self._json_result(self.external_tool_service.oneshot_payload(payload))
        except Exception as e:
            return 0, f'Failed to run external tool oneshot: {e}'

    @desc('Install an external tool package without starting it', group='runtime', suggest=False)
    @interruptible()
    def external_tool_install(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
            return self._json_result(self.external_tool_service.install_payload(payload))
        except Exception as e:
            return 0, f'Failed to install external tool: {e}'

    @desc('Show external tool install status', group='runtime', suggest=False)
    @interruptible()
    def external_tool_install_status(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
            return self._json_result(self.external_tool_service.install_status_payload(payload))
        except Exception as e:
            return 0, f'Failed to get external tool install status: {e}'

    @desc('Clear cached external tool package archive', group='runtime', suggest=False)
    @interruptible()
    def external_tool_clear_cache(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
            return self._json_result(self.external_tool_service.clear_cache_payload(payload))
        except Exception as e:
            return 0, f'Failed to clear external tool cache: {e}'

    @desc('Show external tool install statuses in one client command', group='runtime', suggest=False)
    @interruptible()
    def external_tool_install_statuses(self, arg=''):
        try:
            payload = self.structured_arg_codec.decode(arg)
            return self._json_result(self.external_tool_service.install_statuses_payload(payload))
        except Exception as e:
            return 0, f'Failed to get external tool install statuses: {e}'

    @desc('Stop an external tool instance', group='runtime', suggest=False)
    @interruptible()
    def external_tool_stop(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
            return self._json_result(self.external_tool_service.stop_payload(payload))
        except Exception as e:
            return 0, f'Failed to stop external tool: {e}'

    @desc('Show external tool instance status', group='runtime', suggest=False)
    @interruptible()
    def external_tool_status(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
            return self._json_result(self.external_tool_service.status_from_payload(payload))
        except Exception as e:
            return 0, f'Failed to get external tool status: {e}'

    @desc('List external tool instances', group='runtime', suggest=False)
    @interruptible()
    def external_tool_list_instances(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
            return self._json_result(self.external_tool_service.list_instances_payload(payload))
        except Exception as e:
            return 0, f'Failed to list external tool instances: {e}'

    @desc('List all external tool instances in one command', group='runtime', suggest=False)
    @interruptible()
    def external_tool_list_instances_all(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
            return self._json_result(self.external_tool_service.list_instances_all_payload(payload))
        except Exception as e:
            return 0, f'Failed to list all external tool instances: {e}'

    @desc('Read external tool instance logs', group='runtime', suggest=False)
    @interruptible()
    def external_tool_logs(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
            return self._json_result(self.external_tool_service.read_logs_payload(payload))
        except Exception as e:
            return 0, f'Failed to read external tool logs: {e}'

    @desc('Remove stopped external tool instance runtime files', group='runtime', suggest=False)
    @interruptible()
    def external_tool_remove(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
            return self._json_result(self.external_tool_service.remove_instance_payload(payload))
        except Exception as e:
            return 0, f'Failed to remove external tool instance: {e}'

    @desc('Clear stopped external tool instance logs', group='runtime', suggest=False)
    @interruptible()
    def external_tool_clear_logs(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
            return self._json_result(self.external_tool_service.clear_logs_payload(payload))
        except Exception as e:
            return 0, f'Failed to clear external tool logs: {e}'

    @desc('Show installed external tool executable path', group='runtime', suggest=False)
    @interruptible()
    def external_tool_which(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
            return 1, self.external_tool_service.which_payload(payload)
        except Exception as e:
            return 0, f'Failed to resolve external tool executable: {e}'

    @desc('Run an installed external tool executable with raw argv', group='runtime', suggest=False)
    @interruptible()
    def external_tool_exec(self, arg=''):
        try:
            payload = self._decode_external_tool_payload(arg)
        except Exception:
            self._send_final_result(0, 'Invalid external tool payload')
            return

        self.external_tool_service.execute_cli_payload(payload)
