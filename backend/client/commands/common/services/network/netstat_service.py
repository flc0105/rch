from client.commands.common.providers.netstat_provider import (
    PsutilNetstatProvider,
)
from core.device.local_identity import get_local_identity
from core.utils.command_output import (
    StructuredCommandResult,
    render_structured_result,
)


class NetstatService:
    """
    acmd netstat service.

    约束：
    - Windows / macOS / Linux only
    - psutil only
    - 不套 shell
    - 不 fallback
    - iOS 不支持

    输出字段：
    - protocol
    - local_address
    - remote_address
    - status
    - pid
    """

    def __init__(self, owner=None):
        self.owner = owner

    def build_acmd_netstat_result(self, args_dict):
        port = args_dict.get('port')
        output_json = bool(args_dict.get('json', False))
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

        rows = self.collect_netstat_rows(port=port, status=status, protocol=protocol)

        result = StructuredCommandResult(
            status=1,
            data=rows,
            shape='table',
        )

        return render_structured_result(
            result,
            output_format='json' if output_json else 'text',
        )

    def collect_netstat_rows(self, port=None, status='', protocol=''):
        platform_alias = get_local_identity().os_alias

        if platform_alias == 'ios':
            raise RuntimeError('netstat is unsupported on iOS')

        if platform_alias not in ('win', 'mac', 'linux'):
            raise RuntimeError(
                'Unsupported platform: {}'.format(platform_alias)
            )

        if port is not None:
            port = int(port)

            if port < 0 or port > 65535:
                raise ValueError(
                    'Port out of range: {}'.format(port)
                )

        rows = PsutilNetstatProvider().collect()

        if port is not None:
            rows = [
                row for row in rows
                if self._row_matches_port(row, port)
            ]
        if status:
            # psutil commonly reports LISTEN; accept LISTENING as the CLI spelling.
            statuses = ('LISTEN', 'LISTENING') if status in ('LISTEN', 'LISTENING') else (status,)
            rows = [row for row in rows if (row.get('status') or '').upper() in statuses]
        if protocol:
            rows = [row for row in rows if (row.get('protocol') or '').lower() == protocol]

        rows = self._clean_and_sort_rows(rows)

        if not rows:
            if not status and not protocol:
                if port is None:
                    raise RuntimeError('No TCP/UDP network connections found')
                raise RuntimeError('No TCP/UDP network connections found for port {}'.format(port))
            raise RuntimeError('No network connections match the requested filters')

        return rows

    def _row_matches_port(self, row, port):
        return (
            row.get('_local_port') == port
            or row.get('_remote_port') == port
        )

    def _clean_and_sort_rows(self, rows):
        result = []

        for row in rows or []:
            result.append({
                'protocol': row.get('protocol') or '',
                'local_address': row.get('local_address') or '*:*',
                'remote_address': row.get('remote_address') or '*:*',
                'status': row.get('status') or '-',
                'pid': self._normalize_pid(row.get('pid')),
            })

        result.sort(key=lambda item: (
            item.get('protocol') or '',
            self._address_sort_key(item.get('local_address') or ''),
            self._address_sort_key(item.get('remote_address') or ''),
            item.get('status') or '',
            self._pid_sort_key(item.get('pid')),
        ))

        return result

    def _normalize_pid(self, value):
        if value is None:
            return ''

        try:
            return int(value)
        except Exception:
            return str(value)

    def _pid_sort_key(self, value):
        try:
            return int(value)
        except Exception:
            return -1

    def _address_sort_key(self, value):
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
        else:
            if ':' in text:
                host, port_text = text.rsplit(':', 1)
            else:
                port_text = ''

        try:
            port = int(port_text)
        except Exception:
            port = -1

        return host, port