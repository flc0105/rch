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

        rows = self.collect_netstat_rows(port=port)

        result = StructuredCommandResult(
            status=1,
            data=rows,
            shape='table',
        )

        return render_structured_result(
            result,
            output_format='json' if output_json else 'text',
        )

    def collect_netstat_rows(self, port=None):
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

        rows = self._clean_and_sort_rows(rows)

        if not rows:
            if port is None:
                raise RuntimeError(
                    'No TCP/UDP network connections found'
                )

            raise RuntimeError(
                'No TCP/UDP network connections found for port {}'.format(
                    port
                )
            )

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