"""Server builtin for saved, manually managed TCP Tunnel instances."""
from core.protocol.result_envelope import ResultEnvelope
from core.utils.command_output import render_result_payload, ResultDataShape
from tunnel.instances import instance_service_for, validate_name


class TunnelBuiltinSupport:
    def __init__(self, server, conn, remote_execution_service, history_entry_id_provider):
        self.server = server
        self.conn = conn
        self.remote = remote_execution_service
        self.history_id = history_entry_id_provider

    def execute(self, invocation):
        try:
            args, op = invocation.arguments, invocation.action
            client_id = self.conn.session_info.client_id
            service = instance_service_for(self.server)
            name = args.get('name')
            if op == 'create':
                result = service.create(client_id, name, self._config(args))
            elif op == 'edit':
                result = service.edit(client_id, name, self._config(args))
            elif op == 'remove':
                result = service.remove(client_id, name)
            elif op == 'start':
                supplied = self._config(args)
                created = False
                if supplied:
                    if 'listen_port' not in supplied or 'target_port' not in supplied:
                        raise ValueError('Start with options requires both --listen-port and --target-port')
                    service.create(client_id, name, supplied)
                    created = True
                try:
                    result = service.start(client_id, name, self.remote)
                except Exception:
                    if created:
                        service.remove(client_id, name)
                    raise
            elif op == 'restart':
                result = service.restart(client_id, name, self.remote)
            elif op == 'stop':
                result = service.stop_all(client_id, self.remote) if args.get('all') else service.stop(client_id, name, self.remote)
            elif op == 'status':
                result = service.status(client_id, name) if name else service.list(client_id)
            elif op == 'list':
                result = service.list(client_id)
            else:
                raise ValueError(f'Unsupported tunnel action: {op}')
            envelope = ResultEnvelope(data=result).as_payload()
            return 1, render_result_payload(envelope, invocation.output_format,
                                            view='data', shape=ResultDataShape.FLAT)
        except (OSError, ValueError, RuntimeError) as exc:
            envelope = ResultEnvelope(status='error', message=str(exc)).as_payload()
            return 0, render_result_payload(envelope, invocation.output_format)

    @staticmethod
    def _config(args):
        return {key: args[key] for key in (
            'expose_on', 'listen_host', 'listen_port', 'target_host', 'target_port'
        ) if key in args and args[key] is not None}
