"""Independent data connection for a single managed file transfer."""
from client.config import runtime_config
from client.connection.file_data_connection import open_file_data_connection
from core.protocol.file_stream import receive_control, receive_file, require_ok, send_control, send_file
from core.transfer_settings import FileTransferMode


class TcpFileTransferTransport:
    def __init__(self, owner, transfer_id):
        self.owner = owner
        self.transfer_id = transfer_id
        self.buffer_size = int(runtime_config.HTTP_TRANSFER_BUFFER_SIZE)

    def get_mode_name(self):
        return FileTransferMode.TCP_STREAMING.value

    def is_cancel_supported(self):
        return True

    def configure_context_for_upload(self):
        self.owner.execution_context.set_cancel_policy('cooperative')

    configure_context_for_download = configure_context_for_upload

    def get_buffer_size(self):
        return self.buffer_size

    def _connection(self):
        return open_file_data_connection(self.owner.socket, self.owner.execution_context,
                                         self.transfer_id, self.owner._checkpoint)

    def upload(self, path, *, filename, artifact_type, category, extra, progress_callback):
        with self._connection() as sock:
            send_file(sock, path, metadata={
                'filename': filename, 'artifact_type': artifact_type,
                'category': category, 'extra': extra or {},
            }, checkpoint=self.owner._checkpoint, progress=progress_callback,
                buffer_size=self.buffer_size)
            return require_ok(sock)

    def download(self, path, *, progress_callback, commit=None):
        with self._connection() as sock:
            header = receive_control(sock)
            size = receive_file(sock, path, header, checkpoint=self.owner._checkpoint,
                                progress=progress_callback, buffer_size=self.buffer_size)
            # The existing conflict policy owns the final filesystem mutation.
            # Once the local commit begins, a new cancel request cannot undo it.
            self.owner.execution_context.set_cancel_policy('none', 'File transfer is finalizing')
            self.owner._checkpoint()
            target = commit(path) if commit is not None else path
            try:
                send_control(sock, {'ok': True, 'size': size})
            except OSError:
                # The main connection still reports the committed result.
                pass
            return target
