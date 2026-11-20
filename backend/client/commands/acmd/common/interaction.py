"""Native Client interaction registrations."""

from client.commands.acmd.decorators import argument_command
from client.commands.acmd.standalone.msgbox import msgbox as msgbox_command
from client.commands.acmd.standalone.notify import notify as notify_command
from client.commands.runtime.interrupts import cancel_policy
from client.config import runtime_config
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.protocol.control import ClipboardAction


CLIPBOARD_READ_SPEC = ArgumentCommandSpec(
    name='clipboard_read',
    description='Read clipboard text',
    options=[
        ArgumentOptionSpec('download', 'flag', default=False, help_text='Save clipboard images or files to Artifacts'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
)

CLIPBOARD_WRITE_SPEC = ArgumentCommandSpec(
    name='clipboard_write',
    description='Write clipboard text',
    options=[
        ArgumentOptionSpec('text', 'str', default='', positional_index=0, help_text='Text to write'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
)


def _read_desktop_clipboard(manager):
    return manager.adapter.get_snapshot()


def _read_ios_clipboard(manager):
    import clipboard

    text = clipboard.get()
    if text:
        return {'kind': 'text', 'text': text}
    return manager.adapter.get_snapshot()


class ACMDInteractionCommands:
    msgbox = msgbox_command
    notify = notify_command

    @argument_command('clipboard_read', spec=CLIPBOARD_READ_SPEC, output='stream',
                      platforms=('ios', 'win', 'mac'))
    @cancel_policy('cooperative')
    def clipboard_read(self, args_dict):
        self._set_cancel_policy('cooperative')
        reader = {'ios': _read_ios_clipboard, 'win': _read_desktop_clipboard, 'mac': _read_desktop_clipboard}
        manager = self.socket.runtime.clipboard_manager
        if manager is None:
            return 0, 'Clipboard disabled on Client'

        try:
            with manager.operation(self._checkpoint):
                snapshot = reader[self.command_platform](manager)
            self._checkpoint()

            kind = snapshot.get('kind')
            if kind == 'text':
                return 1, snapshot.get('text') or ''
            if kind not in ('image', 'files'):
                return 1, ''
            if not args_dict['download']:
                if kind == 'image':
                    return 1, 'Clipboard contains an image'
                return 1, f"Clipboard contains {len(snapshot['paths'])} file or folder item(s)"

            status, content = manager.get_clipboard(snapshot=snapshot, checkpoint=self._checkpoint)
            self._checkpoint()
            if not status:
                return 0, f'Failed to read clipboard: {content}'
            if kind == 'image':
                artifact = content.get('artifact')
                if not artifact:
                    return 0, 'Clipboard image is empty'
                name = artifact.get('original_name') or artifact.get('stored_name') or ''
                return 1, f'Clipboard image saved to Artifacts: {name}' if name else 'Clipboard image saved to Artifacts'

            files = content['files']
            if not files:
                return 0, 'No clipboard files are available'
            transfer = self.http_file_transfer_service
            if runtime_config.HTTP_TRANSFER_MODE == 'legacy':
                self._set_cancel_policy('none')
            extra = {'saved_from': 'clipboard'}
            if len(files) == 1 and not files[0]['is_directory']:
                return transfer.upload_single_file_to_server_result(
                    files[0]['path'], category='clipboard', extra=extra,
                )
            return transfer.upload_paths_as_zip_to_server_result(
                [file['path'] for file in files], category='clipboard', extra=extra,
            )
        except (CommandCancelledError, CommandTimeoutError):
            raise
        except Exception as exc:
            return 0, f'Failed to read clipboard: {exc}'

    @argument_command('clipboard_write', spec=CLIPBOARD_WRITE_SPEC, platforms=('ios', 'win', 'mac'))
    @cancel_policy('cooperative')
    def clipboard_write(self, args_dict):
        self._set_cancel_policy('cooperative')
        manager = self.socket.runtime.clipboard_manager
        if manager is None:
            return 0, 'Clipboard disabled on Client'
        try:
            status, result = manager.execute(self, ClipboardAction.SET, {'kind': 'text', 'text': args_dict['text']})
            if status:
                return 1, 'Clipboard updated'
            return 0, f"Failed to write clipboard: {result['message']}"
        except (CommandCancelledError, CommandTimeoutError):
            raise
        except Exception as exc:
            return 0, f'Failed to write clipboard: {exc}'
