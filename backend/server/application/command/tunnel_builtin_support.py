"""Optional Bind Tunnel CLI: management only; forwarding stays inside tunnel/."""
import re

from core.protocol.control import ControlDomain, TunnelAction
from core.protocol.result_envelope import ResultEnvelope
from core.utils.command_output import render_result_payload, ResultDataShape
from server.application.command.command_types import COMMAND_TYPE_CONTROL
from tunnel.server import manager_for

_NAME = re.compile(r'[a-z][a-z0-9_-]{0,31}\Z')


class TunnelBuiltinSupport:
    def __init__(self, server, conn, remote_execution_service, history_entry_id_provider):
        self.server = server
        self.conn = conn
        self.remote = remote_execution_service
        self.history_id = history_entry_id_provider

    @property
    def client_id(self):
        return self.conn.session_info.client_id

    def _control(self, action, payload):
        stream = self.remote.stream_command(
            self.conn, '', command_type=COMMAND_TYPE_CONTROL,
            domain=ControlDomain.TUNNEL, action=action, payload=payload,
            extra={'timeout': 15}, history_entry_id=self.history_id() or '',
        )
        last = None
        for last in stream:
            if getattr(last, 'eof', True) and last[0] != 1:
                value = last[1]
                raise RuntimeError(value.get('message', str(value)) if isinstance(value, dict) else str(value))
        if last is None or last[0] != 1:
            raise RuntimeError('Tunnel Control returned no success')

    @staticmethod
    def _port(value, name):
        if type(value) is not int or not 1 <= value <= 65535:
            raise ValueError(f'{name} must be a port between 1 and 65535')
        return value

    @staticmethod
    def _host(value, name):
        if (not isinstance(value, str) or not value or value != value.strip()
                or len(value) > 253 or any(char.isspace() for char in value)
                or any(char in '/\\@' for char in value)):
            raise ValueError(f'Invalid {name}')
        return value

    @staticmethod
    def _name(value):
        if not isinstance(value, str) or _NAME.fullmatch(value) is None:
            raise ValueError('Mapping name must be 1–32 lowercase letters, digits, - or _ (start with a letter)')
        return value

    def execute(self, invocation):
        try:
            if getattr(self.conn, 'listener_protocol', '') != 'bind_tcp':
                raise ValueError('Tunnel is only available for an online Python Bind Client')
            args = invocation.arguments
            op = invocation.action
            manager = manager_for(self.server)
            if op == 'start':
                name = self._name(args['name'])
                listen_host = self._host(args.get('listen_host') or '127.0.0.1', 'listen host')
                listen_port = self._port(args.get('listen_port'), 'listen port')
                target_host = self._host(args.get('target_host') or '127.0.0.1', 'target host')
                target_port = self._port(args.get('target_port'), 'target port')
                channel_port = self._port(args.get('channel_port') or 9444, 'channel port')
                dial = getattr(self.conn, 'bind_dial_endpoint', None)
                if dial is None:
                    raise ValueError('Bind Client dial endpoint unavailable')
                peer, first = manager.prepare(self.client_id, dial[0], channel_port, name)
                payload = dict(name=name, listen_host=listen_host, listen_port=listen_port,
                               channel_port=channel_port, token=peer.token)
                try:
                    self._control(TunnelAction.START, payload)
                    manager.ready(self.client_id, peer, name, target_host, target_port,
                                  listen_host, listen_port, first=first)
                except Exception:
                    # A Client may already be listening when the Server cannot attach.
                    # Roll back the freshly created listener over the existing RCH control.
                    try:
                        self._control(TunnelAction.STOP, {'name': name})
                    except Exception:
                        pass
                    manager.discard_if_empty(self.client_id, peer)
                    raise
                result = ResultEnvelope(message=(f'Tunnel {name} running: '
                    f'{listen_host}:{listen_port} -> Server {target_host}:{target_port} '
                    f'(channel {channel_port})')).as_payload()
                return 1, render_result_payload(result, invocation.output_format)
            if op == 'stop':
                peer = manager.peer(self.client_id)
                names = ([self._name(args['name'])] if args.get('name') else
                         list(peer.mappings) if peer is not None and args.get('all') else [])
                if not names:
                    raise ValueError('Provide --name NAME or --all')
                for name in names:
                    self._control(TunnelAction.STOP, {'name': name})
                    manager.stopped(self.client_id, name)
                result = ResultEnvelope(message='Stopped: ' + ', '.join(names)).as_payload()
                return 1, render_result_payload(result, invocation.output_format)
            if op in ('list', 'status'):
                snapshot = manager.list(self.client_id)
                if op == 'status' and args.get('name'):
                    name = self._name(args['name'])
                    snapshot['mappings'] = [row for row in snapshot['mappings'] if row['name'] == name]
                    if not snapshot['mappings']:
                        raise ValueError(f'No tunnel mapping named {name}')
                result = ResultEnvelope(data=snapshot).as_payload()
                return 1, render_result_payload(result, invocation.output_format,
                                                 view='data', shape=ResultDataShape.FLAT)
            raise ValueError(f'Unsupported tunnel action: {op}')
        except (OSError, ValueError, RuntimeError) as exc:
            result = ResultEnvelope(status='error', message=str(exc)).as_payload()
            return 0, render_result_payload(result, invocation.output_format)
