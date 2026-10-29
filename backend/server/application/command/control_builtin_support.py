import shlex

from server.application.connection.control_command_store import (
    HTTP_CONTROL_COMMANDS,
    get_control_command_store,
)


HTTP_CONTROL_ACTIONS = {
    'kill': {
        'label': 'Kill',
        'description': 'Terminate the current agent process via remote watchdog.',
    },
    'relaunch': {
        'label': 'Relaunch',
        'description': 'Launch a replacement agent, then terminate the current agent process.',
    },
    'clone': {
        'label': 'Clone',
        'description': 'Launch another agent instance without stopping the current one.',
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
        lines = ['Usage: httpctl <action>', '']
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


    def httpctl(self, arg=''):
        parts = shlex.split(str(arg or '').strip())

        if not parts or parts[0].lower() in ('help', '-h', '--help'):
            yield 1, self._format_httpctl_usage()
            return

        if len(parts) > 1:
            yield 0, self._format_httpctl_usage()
            return

        try:
            action = self._resolve_http_control_action(parts[0])
            client_id = self._get_client_id()

            if not client_id:
                raise ValueError('Missing client_id for current connection')

            payload = self.control_command_store.set_pending_command(
                client_id,
                action['action'],
            )
        except Exception as e:
            yield 0, str(e)
            return

        yield 1, (
            f'httpctl {action["action"]} queued via HTTP control channel '
            f'-> client_id={payload.get("client_id", client_id)}, action={action["action"]}'
        )