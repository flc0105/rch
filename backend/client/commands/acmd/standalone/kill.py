"""ACMD kill: interactive approval and identity-verified process termination."""

from client.commands.acmd.decorators import argument_command
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec


KILL_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='kill', description='Kill processes',
    options=[
        ArgumentOptionSpec(name='pid', option_type='int', default=None, help_text='Process ID'),
        ArgumentOptionSpec(name='name', option_type='str', default='', help_text='Exact process name'),
        ArgumentOptionSpec(name='port', option_type='int', default=None, help_text='Listening port'),
        ArgumentOptionSpec(name='force', option_type='flag', default=False, alias='9', help_text='Use SIGKILL'),
        ArgumentOptionSpec(name='no-confirm', option_type='flag', default=False, help_text='Skip interaction and execute'),
        ArgumentOptionSpec(name='help', option_type='flag', default=False, alias='h', help_text='Show help'),
    ],
    examples=['acmd kill', 'acmd kill --pid 1234', 'acmd kill --name python -9',
              'acmd kill --port 8080 --force', 'acmd kill --pid 1234 --no-confirm'],
)



@argument_command('kill', spec=KILL_ARGUMENT_SPEC, may_interact=True, platforms=('mac', 'win', 'linux'))
def kill(self, args_dict, payload=None):
    from client.runtime.execution.process.approved_process_service import (
        ClientCommandInteractions, ProcessApprovalError, find_targets,
        build_multi_preview, terminate_verified,
    )

    self._set_timeout(240)
    try:
        extra = args_dict.get('_args') or []
        if extra:
            raise ValueError('Unknown kill argument; use --pid, --name, --port, -9, --force or --no-confirm')
        force = bool(args_dict.get('force'))
        no_confirm = bool(args_dict.get('no-confirm'))
        criteria = {key: args_dict[key] for key in ('pid', 'name', 'port')
                    if args_dict.get(key) not in (None, '')}
        if len(criteria) > 1:
            raise ValueError('Specify exactly one of --pid, --name or --port')
        if not criteria and no_confirm:
            raise ValueError('--no-confirm requires --pid, --name or --port')
        if not criteria:
            ui = ClientCommandInteractions(self)
            choice = ui.select('Find a process by:', ['pid', 'name', 'port'],
                               title='Process lookup')
            target = ui.ask(f'Enter {choice}:', title='Process lookup')
            criteria[choice] = target
        if 'pid' in criteria:
            criteria['pid'] = int(criteria['pid'])
        if 'port' in criteria:
            criteria['port'] = int(criteria['port'])
            if not 1 <= criteria['port'] <= 65535:
                raise ProcessApprovalError('Port must be 1..65535')
        if 'name' in criteria:
            criteria['name'] = str(criteria['name']).strip()
            if not criteria['name']:
                raise ValueError('Name must not be empty')
        rows = (find_targets(criteria) if no_confirm
                else find_targets(criteria, preview_limit=100))
        if not rows:
            return 0, 'No matching Client processes'
        if not no_confirm:
            selected_ids, force = ClientCommandInteractions(self).approve_processes(
                'Approve termination of selected Client processes?',
                build_multi_preview(rows, criteria=criteria, force_default=force))
            rows = [row for row in rows if str(row['pid']) in selected_ids]
            if not rows:
                return 1, 'No processes selected; no signal sent.'
        self._checkpoint(fallback_timeout=240)
        outcomes = []
        for row in rows:
            self._checkpoint(fallback_timeout=240)
            try:
                signal_name = terminate_verified(row, force=force, port=criteria.get('port'))
                outcomes.append(f'{signal_name} sent to PID {row["pid"]} ({row["name"]})')
            except (OSError, ProcessApprovalError) as exc:
                outcomes.append(f'PID {row["pid"]} failed: {exc}')
        failures = [line for line in outcomes if ' failed:' in line]
        return (0 if failures else 1), '\n'.join(outcomes)
    except (ValueError, ProcessApprovalError, OSError) as exc:
        return 0, f'Process termination failed: {exc}'
    except Exception as exc:
        return 0, f'Process termination unavailable: {exc}'

