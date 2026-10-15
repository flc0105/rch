"""Ordinary Client commands demonstrating the shared Interaction Broker."""

from client.commands.common.services.interaction_service import CommandInteractions, CommandInteractionError
from core.utils.decorator import desc


class CommandInteractionMixin:

    @desc('Test confirmation and text input before executing a harmless action', group='interaction', api_grants=('interactions:request',))
    def interaction_demo(self, arg=''):
        if str(arg or '').strip():
            return 0, 'Usage: interaction_demo'
        ui = CommandInteractions(self)
        self._set_timeout(240)
        self._send_interim_result(1, '[Interaction Demo] Preview: print a harmless result after approval and input.')
        try:
            if not ui.confirm('Approve the harmless interaction demo?', title='Execution approval'):
                return 0, '[Interaction Demo] Not executed (rejected or expired)'
            label = ui.ask('Enter a label to include in the result:', title='Execution input')
            return 1, f'[Interaction Demo] Executed successfully. Label: {label}'
        except CommandInteractionError as exc:
            return 0, f'[Interaction Demo] Not executed: {exc}'

    @desc('Test select and secret interactions', group='interaction', api_grants=('interactions:request',))
    def interaction_advanced_demo(self, arg=''):
        if str(arg or '').strip():
            return 0, 'Usage: interaction_advanced_demo'
        ui = CommandInteractions(self)
        self._set_timeout(240)
        try:
            choice = ui.select('Choose a harmless demo action:',
                               ['Preview only', 'Execute demo'], title='Select demo mode')
            if choice == 'Preview only':
                return 1, 'Demo preview only; no operation executed.'
            ui.ask('Enter a secret sample (never printed):', title='Secret input demo', secret=True)
            if not ui.confirm('Run harmless demo and discard secret?', title='Demo approval'):
                return 0, 'Demo rejected'
            return 1, 'Demo complete; secret received but not disclosed.'
        except CommandInteractionError as exc:
            return 0, f'Demo cancelled: {exc}'

    @desc('Test structured preview and approval without side effects', group='interaction', api_grants=('interactions:request',))
    def interaction_preview_demo(self, arg=''):
        if str(arg or '').strip():
            return 0, 'Usage: interaction_preview_demo'
        ui = CommandInteractions(self)
        self._set_timeout(240)
        preview = {
            'summary': [
                {'label': 'Items', 'value': '2'},
                {'label': 'Total size', 'value': '12 MiB'},
            ],
            'columns': [{'key': 'item', 'label': 'Item'},
                        {'key': 'files', 'label': 'Files'},
                        {'key': 'size', 'label': 'Size'}],
            'rows': [{'item': 'Documents', 'files': '5', 'size': '3 MiB'},
                     {'item': 'Projects', 'files': '12', 'size': '9 MiB'}],
            'details': [{'title': 'Example entries',
                         'content': 'Documents: /example/Documents\nProjects: /example/Projects'}],
            'notice': 'Demo only; no files, processes or connections will be modified.',
        }
        try:
            accepted = ui.approve_preview('This is a harmless plan preview.',
                                           preview, title='Preview demo')
            return 1, f'Preview demo result: {"approved" if accepted else "rejected"}; no action executed.'
        except CommandInteractionError as exc:
            return 0, f'Preview demo cancelled: {exc}'
