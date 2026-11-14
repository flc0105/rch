import os


from client.config.manager import ConfigurationManager
from core.utils.decorator import desc
from client.runtime.launch_context import is_launchd_managed_client
from client.commands.runtime.interrupts import timeout


class CommandRuntimeConfigMixin:
    """
    client runtime_config 查询与修改命令。
    """

    @property
    def configuration_manager(self):
        runtime = getattr(self.socket, 'runtime', None)
        manager = getattr(runtime, 'configuration_manager', None)
        if manager is None:
            manager = ConfigurationManager(self.socket, getattr(runtime, 'features', None))
        return manager

    @property
    def runtime_config_service(self):
        return self.configuration_manager.service

    @desc('Show or update client runtime config', group='runtime')
    @timeout(30)
    def set(self, arg=''):
        """Render the Configuration Control result for the Client command path."""
        from types import SimpleNamespace
        from core.protocol.control import ConfigurationAction
        from core.protocol.configuration_result import build_configuration_result
        from core.utils.configuration_cli import parse_configuration_request, configuration_cli_items
        from core.utils.command_output import parse_output_format, render_result_payload

        try:
            action, payload, output_format = parse_configuration_request(
                arg, literal_backslashes=(os.name == 'nt'))
        except ValueError as exc:
            return 0, render_result_payload(build_configuration_result(
                ConfigurationAction.GET, status='error', message=str(exc)), parse_output_format(arg))

        messages = []
        scope = SimpleNamespace(_checkpoint=getattr(self, '_checkpoint', lambda: None),
                                _send_interim_result=lambda status, text: messages.append(str(text)))
        status, result = self.configuration_manager.execute(scope, action, payload)
        if status == 1 and action == ConfigurationAction.GET:
            result = {**result, 'data': configuration_cli_items(result['data']), 'shape': 'table'}
        text = render_result_payload(result, output_format)
        if messages and output_format != 'json':
            text = '\n'.join([*messages, text])
        return status, text

    def _apply_runtime_config_side_effects(self, key: str, value):
        return self.configuration_manager.effects(key, value, self._checkpoint, is_launchd_managed_client)
