from core.protocol.message_queue import ResultChunk

from server.application.connection.control_command_store import (
    HTTP_CONTROL_COMMANDS,
    get_control_command_store,
)


HTTP_CONTROL_ACTIONS = {
    'kill': {
        'label': 'Kill',
        'description': 'Terminate the current agent process via Remote Control Watchdog.',
    },
    'relaunch': {
        'label': 'Relaunch',
        'description': 'Launch a replacement agent, then terminate the current agent process.',
    },
    'clone': {
        'label': 'Clone',
        'description': 'Launch another agent instance without stopping the current one.',
    },
    'resume': {
        'label': 'Resume',
        'description': 'Wake the same paused Client process via Remote Control Watchdog.',
    },
}


class ControlBuiltinSupport:
    def __init__(self, conn):
        self.conn = conn
        self.control_command_store = get_control_command_store()


    def _get_client_id(self) -> str:
        session_info = getattr(self.conn, 'session_info', None)
        return str(getattr(session_info, 'client_id', '') or '').strip()


    def _format_httpctl_usage(self) -> str:
        lines = ['Usage: httpctl <action> [--client-id CLIENT_ID for resume]', '']
        for action, spec in HTTP_CONTROL_ACTIONS.items():
            lines.append(f'  {action:<8} {spec["description"]}')
        return '\n'.join(lines)


    def _resolve_http_control_action(self, action: str) -> dict:
        action_text = str(action or '').strip().lower()
        spec = HTTP_CONTROL_ACTIONS.get(action_text)

        if spec is None or action_text not in HTTP_CONTROL_COMMANDS:
            supported = ', '.join(HTTP_CONTROL_ACTIONS.keys())
            raise ValueError(
                f'Unsupported HTTP control action: {action_text or "-"}\n'
                f'{self._format_httpctl_usage()}\n'
                f'Available actions: {supported}'
            )

        return {
            **spec,
            'action': action_text,
        }


    def httpctl(self, invocation):
        from core.protocol.result_envelope import ResultEnvelope
        from core.utils.command_output import render_result_payload

        action_name = invocation.action
        if action_name == 'help':
            envelope = ResultEnvelope(message=self._format_httpctl_usage()).as_payload()
            yield ResultChunk(1, render_result_payload(envelope, invocation.output_format), True,
                              terminal_authoritative=True, event=envelope)
            return

        try:
            action = self._resolve_http_control_action(action_name)
            # Only the resume schema permits an explicit offline Client ID.
            client_id = str(invocation.arguments.get('client-id') or '').strip() or self._get_client_id()
            if not client_id:
                raise ValueError('Missing client_id: select a connection or use resume --client-id CLIENT_ID')
            payload = self.control_command_store.set_pending_command(client_id, action['action'])
            message = (
                f'httpctl {action["action"]} queued via HTTP control channel '
                f'-> client_id={payload.get("client_id", client_id)}, action={action["action"]}'
            )
            status = 1
        except Exception as exc:
            message = str(exc)
            status = 0
        envelope = ResultEnvelope(status='success' if status == 1 else 'error', message=message).as_payload()
        yield ResultChunk(status, render_result_payload(envelope, invocation.output_format), True,
                          terminal_authoritative=True, event=envelope)
