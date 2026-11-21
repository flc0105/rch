import socket

from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.utils.command_output import StructuredCommandResult, ResultDataShape
from client.commands.acmd.decorators import argument_command


NETSTAT_PLATFORMS = ('mac', 'win', 'linux')

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


def format_address(address):
    if not address:
        return '*:*', None

    if isinstance(address, tuple):
        ip = str(address[0] or '') if address else ''
        port = address[1] if len(address) >= 2 else None
    else:
        ip = str(getattr(address, 'ip', '') or '')
        port = getattr(address, 'port', None)

    if not ip:
        ip = '*'

    try:
        port = int(port)
    except Exception:
        port = None

    port_text = '*' if port is None else str(port)
    if ':' in ip and not ip.startswith('['):
        return '[{}]:{}'.format(ip, port_text), port
    return '{}:{}'.format(ip, port_text), port


def connection_record(connection, pid=None):
    try:
        socket_type = int(getattr(connection, 'type', None))
    except Exception:
        return None

    if socket_type == int(socket.SOCK_STREAM):
        protocol = 'tcp'
    elif socket_type == int(socket.SOCK_DGRAM):
        protocol = 'udp'
    else:
        return None

    local_address, local_port = format_address(
        getattr(connection, 'laddr', None)
    )
    remote_address, remote_port = format_address(
        getattr(connection, 'raddr', None)
    )
    status = str(getattr(connection, 'status', None) or '').strip()
    if not status or status.upper() == 'NONE':
        status = '-'

    if pid is None:
        pid = getattr(connection, 'pid', None)

    return {
        'protocol': protocol,
        'local_address': local_address,
        'remote_address': remote_address,
        'status': status,
        'pid': pid,
        'local_port': local_port,
        'remote_port': remote_port,
    }


def collect_connections():
    """Return TCP/UDP connection records using the shared psutil process API.

    Per-process enumeration is used on all supported desktop platforms. On
    macOS, a single protected PID can make psutil's system-wide scan fail; the
    per-process form also lets Windows/Linux retain readable process ownership
    instead of requiring a separate platform-specific collector.
    """
    try:
        import psutil
    except Exception as exc:
        raise RuntimeError('psutil is required: {}'.format(exc)) from exc

    rows = []
    seen = set()
    access_denied_count = 0

    for process in psutil.process_iter(['pid']):
        try:
            pid = process.pid
            get_connections = getattr(process, 'net_connections', None)
            if get_connections is None:
                get_connections = process.connections
            process_connections = get_connections(kind='inet')
        except psutil.AccessDenied:
            access_denied_count += 1
            continue
        except psutil.NoSuchProcess:
            continue
        except Exception:
            continue

        for connection in process_connections or ():
            row = connection_record(connection, pid)
            if row is None:
                continue

            key = (
                row['protocol'], row['local_address'], row['remote_address'],
                row['status'], row['pid'],
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)

    if not rows:
        if access_denied_count:
            raise RuntimeError(
                'psutil could not read network connections; '
                '{} processes were denied by the OS'.format(access_denied_count)
            )
        raise RuntimeError('psutil returned no TCP/UDP network connections')

    return rows


def address_sort_key(value):
    text = str(value or '')
    host = text
    port = -1

    if text.startswith('['):
        end = text.rfind(']:')
        if end >= 0:
            host = text[1:end]
            port_text = text[end + 2:]
        else:
            port_text = ''
    elif ':' in text:
        host, port_text = text.rsplit(':', 1)
    else:
        port_text = ''

    try:
        port = int(port_text)
    except Exception:
        pass

    return host, port


def normalize_pid(value):
    if value is None:
        return ''
    try:
        return int(value)
    except Exception:
        return str(value)


@argument_command(
    'netstat',
    spec=NETSTAT_ARGUMENT_SPEC,
    platforms=NETSTAT_PLATFORMS,
)
def netstat(self, args_dict, payload=None):
    port = args_dict.get('port')
    status = str(args_dict.get('status') or '').strip().upper()
    protocol = str(args_dict.get('protocol') or '').strip().lower()
    listening = bool(args_dict.get('listening'))
    tcp = bool(args_dict.get('tcp'))
    udp = bool(args_dict.get('udp'))

    if listening:
        if status and status not in ('LISTEN', 'LISTENING'):
            raise ValueError('-l conflicts with --status {}'.format(status))
        status = 'LISTENING'

    if protocol and protocol not in ('tcp', 'udp'):
        raise ValueError('Invalid protocol: {} (expected tcp or udp)'.format(protocol))
    if tcp and udp:
        raise ValueError('Choose either -t or -u')
    if tcp or udp:
        selected_protocol = 'tcp' if tcp else 'udp'
        if protocol and protocol != selected_protocol:
            raise ValueError('Conflicting protocol filters')
        protocol = selected_protocol

    if port is not None:
        port = int(port)
        if port < 0 or port > 65535:
            raise ValueError('Port out of range: {}'.format(port))

    rows = collect_connections()

    if port is not None:
        rows = [
            row for row in rows
            if row['local_port'] == port or row['remote_port'] == port
        ]
    if status:
        statuses = ('LISTEN', 'LISTENING') if status in ('LISTEN', 'LISTENING') else (status,)
        rows = [row for row in rows if (row.get('status') or '').upper() in statuses]
    if protocol:
        rows = [row for row in rows if (row.get('protocol') or '').lower() == protocol]

    if not rows:
        if not status and not protocol:
            if port is None:
                raise RuntimeError('No TCP/UDP network connections found')
            raise RuntimeError('No TCP/UDP network connections found for port {}'.format(port))
        raise RuntimeError('No network connections match the requested filters')

    output_rows = [{
        'protocol': row.get('protocol') or '',
        'local_address': row.get('local_address') or '*:*',
        'remote_address': row.get('remote_address') or '*:*',
        'status': row.get('status') or '-',
        'pid': normalize_pid(row.get('pid')),
    } for row in rows]
    output_rows.sort(key=lambda item: (
        item['protocol'],
        address_sort_key(item['local_address']),
        address_sort_key(item['remote_address']),
        item['status'],
        int(item['pid']) if str(item['pid']).isdigit() else -1,
    ))

    return StructuredCommandResult(status=1, data=output_rows, shape=ResultDataShape.TABLE,
                                   formats=('table', 'records', 'json'))
