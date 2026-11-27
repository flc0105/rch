import os
import shutil
import uuid
from threading import RLock

from core.transfer_settings import DEFAULT_HTTP_TRANSFER_BUFFER_SIZE
from server.application.transfers.upload_budget import UploadBudget
from server.config.transfer_limits import (WEB_UPLOAD_STAGING_MAX_BYTES, WEB_UPLOAD_STAGING_MAX_SLOTS,
                                  WEB_UPLOAD_STAGING_MAX_DEVICE_SLOTS)

from werkzeug.utils import secure_filename


class ArtifactTempFileService:
    """
    Artifact 临时文件服务。

    仅负责 upload_tmp 目录下的临时文件：
    - 浏览器上传到 server，准备再下发给 client
    - server 本地文件暂存后给 client 通过 HTTP 拉取
    """

    def __init__(self, artifact_service, *, budget=None):
        self.artifact_service = artifact_service
        self.budget = budget if budget is not None else UploadBudget(
            max_bytes=WEB_UPLOAD_STAGING_MAX_BYTES, max_slots=WEB_UPLOAD_STAGING_MAX_SLOTS,
            max_owner_slots=WEB_UPLOAD_STAGING_MAX_DEVICE_SLOTS)
        self._lock = RLock()
        self._reservations = {}

    def reserve_intake(self, size):
        return self.budget.reserve(size)

    def _build_temp_dir(self) -> str:
        temp_dir = os.path.join(self.artifact_service.upload_tmp_dir, uuid.uuid4().hex)
        os.makedirs(temp_dir, exist_ok=True)
        return temp_dir

    def create_upload_temp_file(self, upload) -> tuple[str, str]:
        """Stage the remaining bytes of a seekable HTTP file stream."""
        stream = upload.stream
        position = stream.tell()
        try:
            size = stream.seek(0, os.SEEK_END) - position
        finally:
            stream.seek(position)
        return self._stage_stream(stream, upload.filename, size)

    def create_upload_temp_path(self, filename: str, *, expected_size: int, owner: str = '') -> tuple[str, str]:
        """Reserve temporary storage before opening a raw HTTP upload body."""
        safe_name = secure_filename(filename or '') or 'upload.bin'
        token = self.budget.acquire(expected_size, owner)
        try:
            with self._lock:
                temp_dir = self._build_temp_dir()
                self._reservations[temp_dir] = token
            return os.path.join(temp_dir, safe_name), safe_name
        except BaseException:
            self.budget.release(token)
            raise

    def _stage_stream(self, stream, display_name, expected_size):
        temp_path, safe_name = self.create_upload_temp_path(display_name, expected_size=expected_size)
        try:
            received = 0
            with open(temp_path, 'wb', buffering=DEFAULT_HTTP_TRANSFER_BUFFER_SIZE) as output:
                while True:
                    chunk = stream.read(DEFAULT_HTTP_TRANSFER_BUFFER_SIZE)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > expected_size:
                        raise ValueError('Upload source grew while staging')
                    output.write(chunk)
            if received != expected_size:
                raise ValueError('Upload source size changed while staging')
            return temp_path, safe_name
        except BaseException:
            self.cleanup_temp_file(temp_path)
            raise

    def stage_local_file(self, source_path: str, display_name: str = '') -> tuple[str, str]:
        """Copy a local source into the reserved upload_tmp area for Client download."""
        abs_source_path = os.path.abspath(source_path)
        if not os.path.isfile(abs_source_path):
            raise FileNotFoundError(f'File not found: {abs_source_path}')
        with open(abs_source_path, 'rb') as source:
            temp_path, safe_name = self._stage_stream(source, display_name or os.path.basename(abs_source_path),
                                                       os.fstat(source.fileno()).st_size)
        try:
            shutil.copystat(abs_source_path, temp_path)
        except BaseException:
            self.cleanup_temp_file(temp_path)
            raise
        return temp_path, safe_name

    def get_temp_file_path(self, temp_id: str, filename: str) -> str:
        """
        根据 temp_id + filename 解析 upload_tmp 下的实际文件路径
        """
        safe_temp_id = secure_filename(temp_id or '')
        safe_name = secure_filename(filename or '')

        if not safe_temp_id or not safe_name:
            raise FileNotFoundError('temp file not found')

        base_dir = os.path.abspath(self.artifact_service.upload_tmp_dir)
        file_path = os.path.abspath(os.path.join(base_dir, safe_temp_id, safe_name))

        if not file_path.startswith(base_dir + os.sep):
            raise ValueError('invalid temp file path')

        if not os.path.isfile(file_path):
            raise FileNotFoundError('temp file not found')

        return file_path

    def build_temp_download_relative_url(self, temp_path: str) -> str:
        """
        根据 upload_tmp 下的临时文件路径生成 HTTP 下载相对地址
        """
        base_dir = os.path.abspath(self.artifact_service.upload_tmp_dir)
        abs_temp_path = os.path.abspath(temp_path)

        if not abs_temp_path.startswith(base_dir + os.sep):
            raise ValueError('temp file is outside upload tmp dir')

        relative_path = os.path.relpath(abs_temp_path, base_dir).replace('\\', '/')
        parts = [part for part in relative_path.split('/') if part]
        if len(parts) < 2:
            raise ValueError('invalid staged temp file path')

        temp_id = parts[0]
        filename = parts[-1]
        return f'/api/upload-tmp/{temp_id}/{filename}'

    def is_temp_file(self, path: str) -> bool:
        if not path:
            return False
        base = os.path.realpath(self.artifact_service.upload_tmp_dir)
        target = os.path.realpath(path)
        # Temporary uploads always have a dedicated directory below upload_tmp.
        return os.path.dirname(os.path.dirname(target)) == base

    def cleanup_temp_file(self, temp_path: str):
        """Release a staging lease only after its dedicated directory is removed."""
        if not self.is_temp_file(temp_path):
            return
        parent_dir = os.path.dirname(os.path.abspath(temp_path))
        with self._lock:
            try:
                shutil.rmtree(parent_dir)
            except FileNotFoundError:
                pass
            except OSError:
                return
            token = self._reservations.pop(parent_dir, None)
            if token is not None:
                self.budget.release(token)

    def is_reserved(self, directory: str) -> bool:
        with self._lock:
            return os.path.abspath(directory) in self._reservations

    def delete_residue_for_cleanup(self, directory, remove):
        directory = os.path.abspath(directory)
        base = os.path.abspath(self.artifact_service.upload_tmp_dir)
        with self._lock:
            if os.path.dirname(directory) != base or directory in self._reservations:
                raise ValueError('Upload staging is active or outside the managed directory')
            remove()
