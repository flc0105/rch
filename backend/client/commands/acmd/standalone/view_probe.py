"""Removable in-process ACMD probe for JSON Viewer presentation and row actions."""
from threading import RLock

from client.commands.acmd.decorators import argument_command
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.utils.command_output import StructuredCommandResult, ResultDataShape


_SPEC = ArgumentCommandSpec(
    name='view_probe', description='Exercise result cards, columns, details and row actions',
    options=[
        ArgumentOptionSpec('delete', 'int', default=None),
        ArgumentOptionSpec('mark', 'int', default=None),
        ArgumentOptionSpec('inspect', 'int', default=None),
        ArgumentOptionSpec('reset', 'flag', default=False),
        ArgumentOptionSpec('plain', 'flag', default=False),
        ArgumentOptionSpec('help', 'flag', default=False),
    ],
    examples=['acmd view_probe --json', 'acmd view_probe --reset --json'],
)
_INITIAL = (
    {'id': 101, 'name': 'Alpha', 'state': 'ready', 'owner': 'operator', 'note': 'Short details'},
    {'id': 102, 'name': 'Bravo', 'state': 'ready', 'owner': 'qa', 'note': 'Details with spaces and punctuation'},
    {'id': 103, 'name': 'Charlie', 'state': 'ready', 'owner': 'reviewer', 'note': 'Long details: ' + 'description ' * 12},
)
_LOCK = RLock()
_ROWS = {item['id']: item.copy() for item in _INITIAL}


@argument_command('view_probe', spec=_SPEC)
def view_probe(self, args_dict):
    """Changes only isolated probe rows in the Client process, not operating-system data."""
    if args_dict.get('_args'):
        return 0, 'Unexpected positional argument'
    operations = (args_dict['delete'] is not None, args_dict['mark'] is not None,
                  args_dict['inspect'] is not None, args_dict['reset'])
    if sum(bool(op) for op in operations) > 1:
        return 0, 'Choose one probe operation'
    with _LOCK:
        if args_dict['reset']:
            _ROWS.clear()
            _ROWS.update({item['id']: item.copy() for item in _INITIAL})
            return 1, 'Probe rows reset'
        if args_dict['delete'] is not None:
            item = _ROWS.pop(args_dict['delete'], None)
            return (1, f'Deleted probe row {item["id"]}') if item else (0, 'Probe row not found')
        if args_dict['mark'] is not None:
            item = _ROWS.get(args_dict['mark'])
            if not item:
                return 0, 'Probe row not found'
            item['state'] = 'marked' if item['state'] == 'ready' else 'ready'
            return 1, f'Updated probe row {item["id"]}'
        if args_dict['inspect'] is not None:
            item = _ROWS.get(args_dict['inspect'])
            if not item:
                return 0, 'Probe row not found'
            return StructuredCommandResult(status=1, data=item.copy(), shape=ResultDataShape.FLAT,
                                           formats=('flat', 'kv', 'json'))
        rows = [item.copy() for item in sorted(_ROWS.values(), key=lambda r: r['id'])]
    view = {
        'titleField': 'name',
        'columns': [{'field': 'id', 'width': 90}, {'field': 'name', 'minWidth': 180},
                    {'field': 'state', 'width': 105}],
        'details': ['owner', 'note'],
    }
    if not args_dict['plain']:
        view['actions'] = [
            {'label': 'Delete', 'command': 'acmd view_probe --delete {id}', 'refresh': True},
            {'label': 'Mark', 'command': 'acmd view_probe --mark {id}', 'refresh': True, 'confirm': False},
            {'label': 'Inspect', 'command': 'acmd view_probe --inspect {id}', 'confirm': False},
            {'label': 'Reset', 'command': 'acmd view_probe --reset', 'refresh': True},
        ]
    return StructuredCommandResult(status=1, data=rows, shape=ResultDataShape.TABLE,
                                   formats=('table', 'records', 'json'), view=view)
