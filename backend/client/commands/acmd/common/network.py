"""ACMD network registration and netstat dispatch."""

from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from client.commands.acmd.decorators import argument_command
from client.commands.common.services.network.netstat_service import NetstatService

NETSTAT_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='netstat',
    description='Show TCP/UDP network connections',
    options=[
        ArgumentOptionSpec(
            name='port',
            option_type='int',
            required=False,
            default=None,
            alias='p',
            positional_index=0,
            help_text='Filter by local or remote port',
        ),
        ArgumentOptionSpec(
            name='status', option_type='str', default='',
            help_text='Filter by status, e.g. LISTENING',
        ),
        ArgumentOptionSpec(
            name='listening', option_type='flag', default=False, alias='l',
            help_text='Show listening connections (-l = --status LISTENING)',
        ),
        ArgumentOptionSpec(
            name='protocol', option_type='str', default='',
            help_text='Filter by protocol: tcp or udp',
        ),
        ArgumentOptionSpec(
            name='tcp', option_type='flag', default=False, alias='t',
            help_text='Show TCP connections (-t = --protocol tcp)',
        ),
        ArgumentOptionSpec(
            name='udp', option_type='flag', default=False, alias='u',
            help_text='Show UDP connections (-u = --protocol udp)',
        ),
        ArgumentOptionSpec(
            name='json',
            option_type='flag',
            required=False,
            default=False,
            help_text='Output as JSON',
        ),
        ArgumentOptionSpec(
            name='help',
            option_type='flag',
            required=False,
            default=False,
            alias='h',
            help_text='Show this help message',
        ),
    ],
    examples=[
        'acmd netstat',
        'acmd netstat 443',
        'acmd netstat --port 443',
        'acmd netstat --port 443 --json',
        'acmd netstat --status LISTENING',
        'acmd netstat -l -t',
        'acmd netstat --protocol udp',
    ],
)


class ACMDNetworkCommands:
    @argument_command('netstat', spec=NETSTAT_ARGUMENT_SPEC)
    def _acmd_netstat(self, args_dict, payload=None):
        return self._acmd_netstat_common(args_dict, payload)

    def _get_netstat_service(self):
        service = getattr(self, '_netstat_service', None)

        if service is None:
            service = NetstatService(self)
            self._netstat_service = service

        return service


    def _acmd_netstat_common(self, args_dict, payload=None):
        """
        acmd netstat 公共实现。

        注意：
        - 不在这里加 @argument_command
        - iOS 不注册 netstat
        - mac / linux / win 通过共享 ACMD 注册类导出
        """
        return self._get_netstat_service().build_acmd_netstat_result(args_dict)