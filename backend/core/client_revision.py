import hashlib
import os
from core.agent_build_contract import AGENT_FILENAME_STEM, AgentBuilderKind, agent_output_filename


CLIENT_BUNDLE_SOURCE_PATHS = (
    'client',
    'core',
    'tunnel',
    'rchclient.py',
)
CLIENT_REVISION_EXCLUDE_PATHS = {
    'client/config',
}
CLIENT_REVISION_EXCLUDE_DIRS = {
    '__pycache__',
    '.git',
    '.idea',
    '.vscode',
    'venv',
    'node_modules',
    'dist',
    'build',
}
CLIENT_REVISION_EXCLUDE_FILES = {
    '.DS_Store',
}
CLIENT_REVISION_EXCLUDE_EXTENSIONS = {
    '.pyc',
    '.pyo',
    '.pyd',
}
REVISION_DIGEST_LENGTH = 16

# The downloadable archive keeps the agent name; build_version remains builder-based.
PYTHON_ARTIFACT_STEM = f'{AGENT_FILENAME_STEM}_{AgentBuilderKind.PYTHON.value}'


def bundle_archive_name(build_id: str) -> str:
    return agent_output_filename(AgentBuilderKind.PYTHON, build_id, suffix='.zip')


def is_bundle_archive(name: str) -> bool:
    return (isinstance(name, str) and name.startswith(PYTHON_ARTIFACT_STEM + '_')
            and name.lower().endswith('.zip'))


def _get_default_source_root() -> str:
    core_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(core_dir)


def _normalize_relative_path(path: str) -> str:
    return str(path or '').replace('\\', '/').strip('/')


def _is_excluded_path(relative_path: str) -> bool:
    normalized = _normalize_relative_path(relative_path)
    if not normalized:
        return False

    for excluded_path in CLIENT_REVISION_EXCLUDE_PATHS:
        excluded = _normalize_relative_path(excluded_path)
        if normalized == excluded or normalized.startswith(f'{excluded}/'):
            return True

    parts = normalized.split('/')
    if any(part in CLIENT_REVISION_EXCLUDE_DIRS for part in parts):
        return True
    if parts[-1] in CLIENT_REVISION_EXCLUDE_FILES:
        return True

    extension = os.path.splitext(parts[-1])[1].lower()
    return extension in CLIENT_REVISION_EXCLUDE_EXTENSIONS


def _iter_revision_files(source_root: str, relative_path: str):
    normalized_path = _normalize_relative_path(relative_path)
    if not normalized_path or _is_excluded_path(normalized_path):
        return

    target_path = os.path.join(source_root, *normalized_path.split('/'))

    if os.path.isfile(target_path):
        yield target_path
        return

    if not os.path.isdir(target_path):
        return

    for root, dirs, files in os.walk(target_path):
        kept_dirs = []
        for name in sorted(dirs):
            child_path = os.path.relpath(os.path.join(root, name), source_root)
            child_relative = _normalize_relative_path(child_path)
            if name in CLIENT_REVISION_EXCLUDE_DIRS or _is_excluded_path(child_relative):
                continue
            kept_dirs.append(name)
        dirs[:] = kept_dirs

        for name in sorted(files):
            file_path = os.path.join(root, name)
            relative_file = _normalize_relative_path(os.path.relpath(file_path, source_root))
            if _is_excluded_path(relative_file):
                continue
            yield file_path


def _hash_file(file_path: str) -> str:
    digest = hashlib.sha256()
    with open(file_path, 'rb') as file_obj:
        while True:
            chunk = file_obj.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()[:REVISION_DIGEST_LENGTH]


def _hash_files(source_root: str, relative_paths, *, file_stats=None) -> str:
    digest = hashlib.sha256()
    matched = False

    for relative_path in relative_paths:
        for file_path in _iter_revision_files(source_root, relative_path):
            matched = True
            relative_file = _normalize_relative_path(os.path.relpath(file_path, source_root))
            digest.update(relative_file.encode('utf-8'))
            digest.update(b'\0')
            if file_stats is not None:
                stat = os.stat(file_path)
                file_stats[relative_file] = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
            with open(file_path, 'rb') as file_obj:
                while True:
                    chunk = file_obj.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            digest.update(b'\0')

    if not matched:
        digest.update(b'EMPTY')

    return digest.hexdigest()[:REVISION_DIGEST_LENGTH]



def build_client_revision_manifest(
    source_root: str = '',
    include_files: bool = True,
    file_stats: dict | None = None,
) -> dict:
    """
    计算 Client 源码 revision。

    按实际 Client bundle 根目录递归计算，新增/删除运行代码路径会自动纳入；
    client/config 单独排除，避免仅修改连接地址、profile 或运行配置时误判为源码更新。
    """
    root = os.path.abspath(source_root or _get_default_source_root())
    files = {}
    if include_files:
        for relative_root in CLIENT_BUNDLE_SOURCE_PATHS:
            for file_path in _iter_revision_files(root, relative_root):
                relative_file = _normalize_relative_path(os.path.relpath(file_path, root))
                files[relative_file] = _hash_file(file_path)

    return {
        'revision': _hash_files(root, CLIENT_BUNDLE_SOURCE_PATHS, file_stats=file_stats),
        'files': files,
    }
