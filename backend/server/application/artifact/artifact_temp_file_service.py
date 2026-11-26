import os
import shutil
import uuid

from werkzeug.utils import secure_filename


class ArtifactTempFileService:
    """
    Artifact 临时文件服务。

    仅负责 upload_tmp 目录下的临时文件：
    - 浏览器上传到 server，准备再下发给 client
    - server 本地文件暂存后给 client 通过 HTTP 拉取
    """

    def __init__(self, artifact_service):
        self.artifact_service = artifact_service

    def _build_temp_dir(self) -> str:
        temp_dir = os.path.join(self.artifact_service.upload_tmp_dir, uuid.uuid4().hex)
        os.makedirs(temp_dir, exist_ok=True)
        return temp_dir

    def create_upload_temp_file(self, upload) -> tuple[str, str]:
        """
        为浏览器上传文件创建临时落盘文件
        :return: (temp_path, safe_name)
        """
        safe_name = secure_filename(upload.filename) or 'upload.bin'
        temp_dir = self._build_temp_dir()
        temp_path = os.path.join(temp_dir, safe_name)
        upload.save(temp_path)
        return temp_path, safe_name

    def create_upload_temp_path(self, filename: str) -> tuple[str, str]:
        """
        为原始 HTTP body 上传预分配临时落盘路径。
        :return: (temp_path, safe_name)
        """
        safe_name = secure_filename(filename or '') or 'upload.bin'
        temp_dir = self._build_temp_dir()
        return os.path.join(temp_dir, safe_name), safe_name

    def stage_local_file(self, source_path: str, display_name: str = '') -> tuple[str, str]:
        """
        将服务端本地文件复制到 upload_tmp 暂存区，供 client 通过 HTTP 拉取
        :return: (temp_path, safe_name)
        """
        abs_source_path = os.path.abspath(source_path)
        if not os.path.isfile(abs_source_path):
            raise FileNotFoundError(f'File not found: {abs_source_path}')

        safe_name = secure_filename(display_name or os.path.basename(abs_source_path)) or 'upload.bin'
        temp_dir = self._build_temp_dir()
        temp_path = os.path.join(temp_dir, safe_name)
        shutil.copy2(abs_source_path, temp_path)
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
        """
        清理单个临时文件及其上层临时目录
        """
        if not self.is_temp_file(temp_path):
            return

        try:
            if os.path.isfile(temp_path):
                os.remove(temp_path)
        except Exception:
            pass

        try:
            parent_dir = os.path.dirname(temp_path)
            base_dir = os.path.abspath(self.artifact_service.upload_tmp_dir)
            abs_parent_dir = os.path.abspath(parent_dir)

            if abs_parent_dir.startswith(base_dir + os.sep) and os.path.isdir(abs_parent_dir):
                shutil.rmtree(abs_parent_dir, ignore_errors=True)
        except Exception:
            pass









