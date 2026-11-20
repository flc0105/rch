"""Common ACMD network command registrations."""

import socket
import time

from client.commands.acmd.decorators import argument_command
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from client.commands.acmd.standalone.ifconfig import ifconfig
from client.commands.acmd.standalone.netstat import netstat


TCP_CHECK_SPEC = ArgumentCommandSpec(
    name='tcp_check',
    description='Check whether a TCP port is reachable from this Client',
    options=[
        ArgumentOptionSpec('port', 'int', required=True, positional_index=0, help_text='TCP port'),
        ArgumentOptionSpec('host', 'str', default='localhost', allow_empty=False,
                           help_text='Target hostname or IP address (default: localhost)'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
    examples=['acmd tcp_check 8080', 'acmd tcp_check --port 443 --host example.com'],
)


@argument_command('tcp_check', spec=TCP_CHECK_SPEC)
def tcp_check(self, args_dict):
    port = args_dict['port']
    if not 1 <= port <= 65535:
        return 0, '--port must be between 1 and 65535'
    host = args_dict['host'].strip()
    endpoint = f'[{host}]:{port}' if ':' in host else f'{host}:{port}'
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=5):
            elapsed_ms = (time.monotonic() - started) * 1000
            return 1, f'{endpoint} is reachable ({elapsed_ms:.0f} ms).'
    except socket.gaierror:
        return 0, f'Could not resolve {host}.'
    except ConnectionRefusedError:
        return 0, f'Connection refused by {endpoint}.'
    except TimeoutError:
        return 0, f'Connection to {endpoint} timed out.'
    except OSError as exc:
        return 0, f'Could not connect to {endpoint}: {exc.strerror or exc}'


def register_commands(registry):
    """Register declarations owned by this Common / Platform module."""
    registry.register(ifconfig)
    registry.register(netstat)
    registry.register(tcp_check)
