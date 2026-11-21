"""macOS-only ACMD launchd entry: options, approval and result rendering."""

from client.commands.acmd.decorators import argument_command
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.utils.command_output import StructuredCommandResult, ResultDataShape


LAUNCHD_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='launchd',
    description='Manage a macOS LaunchAgent or LaunchDaemon',
    options=[
        # Required execution choices are collected through Interaction Broker if omitted.
        ArgumentOptionSpec(name='action', option_type='str', required=True, default='', allow_empty=False,
                           positional_index=0, help_text='install, start, stop, restart, uninstall, status'),
        ArgumentOptionSpec(name='kind', option_type='str', required=True, default='', allow_empty=False,
                           positional_index=1, help_text='agent or daemon'),
        ArgumentOptionSpec(name='label', option_type='str', default='com.rch.client', allow_empty=False,
                           help_text='launchd service label'),
        ArgumentOptionSpec(name='keep_alive', option_type='bool', default=True,
                           help_text='Set KeepAlive when installing'),
        ArgumentOptionSpec(name='run_at_load', option_type='bool', default=True,
                           help_text='Set RunAtLoad when installing'),
        ArgumentOptionSpec(name='scope', option_type='str', default='user', allow_empty=False,
                           help_text='LaunchAgent scope: user or global'),
        ArgumentOptionSpec(name='target_user', option_type='str', default='', allow_empty=True,
                           help_text='LaunchAgent target username or UID; blank selects current GUI user'),
        ArgumentOptionSpec(name='no-confirm', option_type='flag', default=False,
                           help_text='Execute directly; requires action and kind'),
        ArgumentOptionSpec(name='help', option_type='flag', default=False,
                           help_text='Show this help message'),
    ],
    examples=[
        'acmd launchd install agent --scope user --keep-alive true',
        'acmd launchd --action start --kind agent',
        'acmd launchd status daemon',
        'acmd launchd uninstall agent --label com.rch.client',
        'acmd launchd status agent --json',
    ],
)


@argument_command('launchd', spec=LAUNCHD_ARGUMENT_SPEC, interaction=True, platforms=('mac',))
def launchd(self, args_dict, payload=None):
    from client.runtime.sdk import launchd

    action = str(args_dict.get('action') or '').strip().lower()
    kind = str(args_dict.get('kind') or '').strip().lower()
    no_confirm = bool(args_dict.get('no-confirm'))
    if action and action not in launchd.VALID_LAUNCHD_ACTIONS:
        return 0, f'Invalid launchd action: {action} (install, start, stop, restart, uninstall, status)'
    if kind and kind not in ('agent', 'daemon'):
        return 0, f'Invalid launchd kind: {kind} (agent, daemon)'
    if no_confirm and (not action or not kind):
        return 0, '--no-confirm requires both action and kind'

    if not no_confirm:
        # This import and every Broker request are bypassed for --no-confirm.
        from client.runtime.execution.interaction_service import (
            CommandInteractions, CommandInteractionError,
        )
        self._set_timeout(300)
        ui = CommandInteractions(self)
        try:
            if not action:
                action = ui.select('Choose the launchd action:',
                                   ['install', 'start', 'stop', 'restart', 'uninstall', 'status'],
                                   title='Launchd action')
            if not kind:
                kind = ui.select('Choose the launchd service type:',
                                 ['agent', 'daemon'], title='Launchd type')

            preview = {
                'summary': [
                    {'label': 'Action', 'value': action},
                    {'label': 'Type', 'value': 'LaunchAgent' if kind == 'agent' else 'LaunchDaemon'},
                    {'label': 'Label', 'value': args_dict['label']},
                    {'label': 'KeepAlive', 'value': str(args_dict['keep_alive']).lower()},
                    {'label': 'RunAtLoad', 'value': str(args_dict['run_at_load']).lower()},
                ],
                'notice': ('KeepAlive and RunAtLoad apply when installing. '
                           'Stopping or uninstalling the running Client may disconnect this session.'),
            }
            if kind == 'agent':
                preview['summary'].extend([
                    {'label': 'Scope', 'value': args_dict['scope']},
                    {'label': 'Target user', 'value': args_dict['target_user'] or 'Current GUI user (automatic)'},
                ])
            if not ui.approve_preview('Approve this launchd operation?', preview,
                                      title='Review launchd operation'):
                return 0, 'launchd action not approved; no changes made'
        except CommandInteractionError as exc:
            return 0, f'launchd interaction cancelled or unavailable: {exc}'

    try:
        self._checkpoint(fallback_timeout=300)
        result = launchd.manage(
            kind=kind,
            action=action,
            label=args_dict['label'],
            scope=args_dict['scope'] if kind == 'agent' else 'user',
            target_user=(args_dict['target_user'] or None) if kind == 'agent' else None,
            keep_alive=args_dict['keep_alive'],
            run_at_load=args_dict['run_at_load'],
        )
        status = 1 if result.get('ok') else 0
        return StructuredCommandResult(
            status=status, data=result, shape=ResultDataShape.FLAT,
            source='message', message=launchd.format_result(result),
            formats=('message', 'flat', 'kv', 'json'), width=20,
        )
    except (ValueError, OSError, RuntimeError) as exc:
        return 0, f'launchd {action or "operation"} failed: {exc}'
