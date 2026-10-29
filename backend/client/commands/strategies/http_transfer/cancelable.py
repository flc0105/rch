import os
import uuid

import requests

from client.commands.runtime.context import CommandCancelledError
from client.commands.strategies.http_transfer.base import HttpTransferStrategy


class CancelableMultipartUploadStream:
    """
    可取消的 multipart/form-data 流。
    """

    def __init__(self, owner, file_path: str, form_data: dict, chunk_size: int, progress_callback=None):
        self.owner = owner
        self.file_path = file_path
        self.form_data = form_data or {}
        self.chunk_size = max(int(chunk_size or 1), 1)
        self.boundary = f'----ratboundary{uuid.uuid4().hex}'
        self.file_name = os.path.basename(file_path)
        self.file_size = os.path.getsize(file_path)
        self.progress_callback = progress_callback
        self._file_bytes_read = 0

        self._opened_file = None
        self._prefix = self._build_prefix_bytes()
        self._suffix = self._build_suffix_bytes()
        self._prefix_offset = 0
        self._suffix_offset = 0
        self._file_finished = False

    def _build_prefix_bytes(self) -> bytes:
        lines = []

        for key, value in self.form_data.items():
            lines.append(f'--{self.boundary}\r\n'.encode('utf-8'))
            lines.append(
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode('utf-8')
            )
            lines.append(str(value).encode('utf-8'))
            lines.append(b'\r\n')

        lines.append(f'--{self.boundary}\r\n'.encode('utf-8'))
        lines.append(
            (
                'Content-Disposition: form-data; '
                f'name="file"; filename="{self.file_name}"\r\n'
            ).encode('utf-8')
        )
        lines.append(b'Content-Type: application/octet-stream\r\n\r\n')
        return b''.join(lines)

    def _build_suffix_bytes(self) -> bytes:
        return f'\r\n--{self.boundary}--\r\n'.encode('utf-8')

    @property
    def content_type(self) -> str:
        return f'multipart/form-data; boundary={self.boundary}'

    @property
    def content_length(self) -> int:
        return len(self._prefix) + self.file_size + len(self._suffix)

    def __len__(self) -> int:
        return self.content_length

    def close(self):
        try:
            if self._opened_file is not None:
                self._opened_file.close()
        except Exception:
            pass
        finally:
            self._opened_file = None

    def _open_file_if_needed(self):
        if self._opened_file is None and not self._file_finished:
            self._opened_file = open(self.file_path, 'rb')

    def _read_from_prefix(self, size: int) -> bytes:
        if self._prefix_offset >= len(self._prefix):
            return b''

        end = min(self._prefix_offset + size, len(self._prefix))
        data = self._prefix[self._prefix_offset:end]
        self._prefix_offset = end
        return data

    def _read_from_file(self, size: int) -> bytes:
        if self._file_finished:
            return b''

        self._open_file_if_needed()
        self.owner._ensure_not_cancelled()
        data = self._opened_file.read(size)
        self.owner._ensure_not_cancelled()
        if data:
            self._file_bytes_read += len(data)
            if callable(self.progress_callback):
                self.progress_callback(self._file_bytes_read, self.file_size)
            return data

        self._file_finished = True
        self.close()
        return b''

    def _read_from_suffix(self, size: int) -> bytes:
        if self._suffix_offset >= len(self._suffix):
            return b''

        end = min(self._suffix_offset + size, len(self._suffix))
        data = self._suffix[self._suffix_offset:end]
        self._suffix_offset = end
        return data

    def read(self, size: int = -1) -> bytes:
        self.owner._ensure_not_cancelled()

        if size is None or size < 0:
            size = self.chunk_size

        if size == 0:
            return b''

        parts = []
        remaining = size

        while remaining > 0:
            self.owner._ensure_not_cancelled()

            chunk = self._read_from_prefix(remaining)
            if not chunk:
                chunk = self._read_from_file(remaining)
            if not chunk:
                chunk = self._read_from_suffix(remaining)
            if not chunk:
                break

            parts.append(chunk)
            remaining -= len(chunk)

        return b''.join(parts)


class CancelableHttpTransferStrategy(HttpTransferStrategy):
    MODE_NAME = 'cancelable'

    def is_cancel_supported(self) -> bool:
        return True

    def _create_session(self):
        session = self.create_http_session()
        self.owner._register_cancel_handler(lambda: session.close())
        self.owner._register_cleanup_handler(lambda: session.close())
        return session

    def upload_file(self, file_path: str, upload_url: str, form_data: dict, progress_callback=None):
        self.configure_context_for_upload()
        self.owner._ensure_not_cancelled()

        session = self._create_session()
        response = None
        stream = CancelableMultipartUploadStream(
            self.owner,
            file_path,
            form_data,
            chunk_size=self.get_buffer_size(),
            progress_callback=progress_callback,
        )
        self.owner._register_cancel_handler(stream.close)
        self.owner._register_cleanup_handler(stream.close)

        try:
            response = session.post(
                upload_url,
                data=stream,
                headers={
                    'Content-Type': stream.content_type,
                    'Content-Length': str(stream.content_length),
                },
            )
            self.owner._ensure_not_cancelled()
            return response
        except CommandCancelledError:
            raise
        except requests.RequestException as e:
            self.owner._ensure_not_cancelled()
            raise
        finally:
            try:
                stream.close()
            except Exception:
                pass
            try:
                if response is not None:
                    response.close()
            except Exception:
                pass
            session.close()

    def download_file(self, url: str, target_path: str, progress_callback=None):
        self.configure_context_for_download()
        self.owner._ensure_not_cancelled()

        session = self._create_session()
        response = None
        file_obj = None
        try:
            response = session.get(
                url,
                stream=True,
            )
            response.raise_for_status()

            total_bytes = 0
            try:
                total_bytes = max(0, int(response.headers.get('Content-Length') or 0))
            except Exception:
                total_bytes = 0
            transferred_bytes = 0

            file_obj = open(target_path, 'wb')
            self.owner._register_cleanup_handler(lambda: file_obj.close())
            self.owner._register_cancel_handler(lambda: file_obj.close())

            for chunk in response.iter_content(chunk_size=self.get_buffer_size()):
                self.owner._ensure_not_cancelled()
                if not chunk:
                    continue
                file_obj.write(chunk)
                transferred_bytes += len(chunk)
                if callable(progress_callback):
                    progress_callback(transferred_bytes, total_bytes)

            self.owner._ensure_not_cancelled()
            file_obj.close()
            file_obj = None
        except CommandCancelledError:
            raise
        except requests.RequestException as e:
            self.owner._ensure_not_cancelled()
            raise
        finally:
            if file_obj is not None:
                try:
                    file_obj.close()
                except Exception:
                    pass
            try:
                if response is not None:
                    response.close()
            except Exception:
                pass
            session.close()
