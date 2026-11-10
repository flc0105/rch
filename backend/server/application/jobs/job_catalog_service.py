import glob
import os
from pathlib import Path

from werkzeug.utils import secure_filename

from core.utils.job_metadata import read_job_metadata_from_file, normalize_job_key


class JobCatalogService:

    def __init__(self, jobs_root_dir: str):
        self.jobs_root_dir = os.path.abspath(jobs_root_dir)
        self._ensure_dir()

    def _ensure_dir(self):
        """确保任务目录存在"""
        os.makedirs(self.jobs_root_dir, exist_ok=True)

    def _build_job_item(self, file_path: str) -> dict:
        rel_path = os.path.relpath(file_path, self.jobs_root_dir)
        name = rel_path.replace('\\', '/')
        job_name = name[:-3] if name.endswith('.py') else name
        metadata = read_job_metadata_from_file(file_path, fallback_name=job_name)

        display_name = str(metadata.get('display_name') or name).strip() or name
        description = str(metadata.get('description') or '').strip()

        return {
            'name': job_name,
            'job_name': job_name,
            'job_key': job_name,
            'display_name': display_name,
            'description': description,
            'metadata': metadata,
            'path': file_path,
            'size': os.path.getsize(file_path),
            'source': 'job',
            'kind': 'background_job',
        }

    def list_jobs(self) -> list[dict]:
        """列出所有可用的任务。"""
        jobs = []
        pattern = os.path.join(self.jobs_root_dir, '**/*.py')
        for file_path in glob.iglob(pattern, recursive=True):
            if not os.path.isfile(file_path):
                continue
            jobs.append(self._build_job_item(file_path))
        return sorted(jobs, key=lambda x: x['job_name'])

    def list_background_job_catalog(self) -> list[dict]:
        normalized = []
        seen = set()
        for item in self.list_jobs() or []:
            if not isinstance(item, dict):
                continue
            job_name = str(item.get('job_name') or item.get('name') or item.get('job_key') or '').strip()
            if not job_name or job_name in seen:
                continue
            seen.add(job_name)
            normalized.append({
                **item,
                'job_name': job_name,
                'job_key': str(item.get('job_key') or job_name).strip() or job_name,
                'display_name': str(item.get('display_name') or item.get('name') or job_name).strip() or job_name,
                'description': str(item.get('description') or '').strip(),
                'metadata': item.get('metadata') or {},
                'source': 'job',
            })
        normalized.sort(key=lambda item: item.get('job_name', '').lower())
        return normalized

    def get_job_metadata(self, job_name: str) -> dict:
        target = normalize_job_key(job_name)
        for item in self.list_jobs() or []:
            if not isinstance(item, dict):
                continue
            candidate = normalize_job_key(item.get('job_name') or item.get('name') or '')
            if candidate == target:
                metadata = item.get('metadata') or {}
                return metadata if isinstance(metadata, dict) else {}
        return {}

    def get_job_content(self, job_name: str) -> str:
        """
        获取任务内容
        """
        safe_name = self._normalize_job_name(job_name)
        if not safe_name:
            raise ValueError('Invalid job name')
        job_path = os.path.join(self.jobs_root_dir, safe_name)
        job_path = os.path.abspath(job_path)

        if not job_path.startswith(self.jobs_root_dir + os.sep):
            raise ValueError('Invalid job path')

        if not os.path.isfile(job_path):
            raise FileNotFoundError(f'Job not found: {job_name}')

        with open(job_path, 'r', encoding='utf-8') as f:
            return f.read()

    def _normalize_job_name(self, name: str) -> str:
        """
        规范化任务名称，防止路径遍历
        """
        name = str(name or '').replace('\\', '/').lstrip('/')
        parts = []
        for part in name.split('/'):
            part = part.strip()
            if not part or part in ('.', '..'):
                continue
            parts.append(part)

        normalized = '/'.join(parts)
        if normalized.endswith('.py'):
            return normalized
        return normalized + '.py' if normalized else ''

    def _resolve_job_path_for_write(self, job_name: str) -> tuple[str, str]:
        safe_name = self._normalize_job_name(job_name)
        if not safe_name:
            raise ValueError('Invalid job name')

        job_path = os.path.abspath(os.path.join(self.jobs_root_dir, safe_name))
        if not job_path.startswith(self.jobs_root_dir + os.sep):
            raise ValueError('Invalid job path')

        os.makedirs(os.path.dirname(job_path), exist_ok=True)
        return safe_name, job_path

    def save_job(self, job_name: str, content: str) -> dict:
        """
        保存任务（用于前端编辑 / 新建）
        """
        safe_name, job_path = self._resolve_job_path_for_write(job_name)

        with open(job_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return {
            'name': safe_name,
            'path': job_path,
            'size': os.path.getsize(job_path),
        }

    def upload_job(self, file_storage) -> dict:
        """上传一个 .py 任务到 jobs 目录。"""
        if file_storage is None:
            raise ValueError('file is required')

        original_name = str(getattr(file_storage, 'filename', '') or '').strip()
        if not original_name:
            raise ValueError('filename is required')

        safe_filename = secure_filename(Path(original_name).name)
        if not safe_filename:
            raise ValueError('Invalid filename')
        if not safe_filename.lower().endswith('.py'):
            raise ValueError('Only .py files are supported')

        safe_name, job_path = self._resolve_job_path_for_write(safe_filename)
        file_storage.save(job_path)

        return {
            'name': safe_name,
            'path': job_path,
            'size': os.path.getsize(job_path),
        }

    def _resolve_job_path(self, job_name: str) -> tuple[str, str]:
        """
        解析任务路径（读取/删除用）
        """
        safe_name = self._normalize_job_name(job_name)
        if not safe_name:
            raise ValueError('Invalid job name')

        job_path = os.path.abspath(os.path.join(self.jobs_root_dir, safe_name))
        if not job_path.startswith(self.jobs_root_dir + os.sep):
            raise ValueError('Invalid job path')

        return safe_name, job_path

    def delete_job(self, job_name: str) -> dict:
        """
        删除一个后台任务脚本
        """
        safe_name, job_path = self._resolve_job_path(job_name)

        if not os.path.isfile(job_path):
            raise FileNotFoundError(f'Job not found: {job_name}')

        os.remove(job_path)

        return {
            'name': safe_name[:-3] if safe_name.endswith('.py') else safe_name,
            'display_name': safe_name,
            'path': job_path,
            'deleted': True,
        }
