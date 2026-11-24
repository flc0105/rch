import os
import tempfile

from core.protocol.structured_arg_codec import StructuredArgCodec
from core.utils.logger import logger


def reported_current_directory() -> str:
    """Read CWD for protocol metadata without changing process state."""
    try:
        return os.getcwd()
    except OSError:
        return ''


def recover_current_directory() -> str:
    """Restore an invalid process CWD at a foreground execution boundary."""
    cwd = reported_current_directory()
    if cwd:
        return cwd

    for resolve in (lambda: os.path.expanduser('~'), tempfile.gettempdir):
        try:
            candidate = resolve()
            if not os.path.isabs(candidate):
                continue
            os.chdir(candidate)
            cwd = reported_current_directory()
            if cwd:
                logger.warning('Current working directory unavailable; changed to %s', cwd)
                return cwd
        except OSError:
            continue
    return ''


class PathResolver:
    """
    路径解析与存在性校验服务。
    """

    def __init__(self, codec: StructuredArgCodec | None = None, iter_checked=None):
        self.codec = codec or StructuredArgCodec()
        self.iter_checked = iter_checked

    def _iter(self, iterable, check_interval: int = 1):
        if self.iter_checked is None:
            return iterable
        return self.iter_checked(iterable, check_interval=check_interval)

    def validate_directory_exists(self, path):
        directory = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(directory):
            raise FileNotFoundError(f'Directory not found: {directory}')
        return directory

    def validate_file_exists(self, path):
        file_path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f'File not found: {file_path}')
        return file_path

    def resolve_target_path(self, path: str, *, base_dir=None) -> str:
        raw_path = (path or '').strip()
        # 空路径保留“当前工作目录”语义，供浏览等非破坏性命令使用。
        if not raw_path:
            raw_path = '.'

        expanded_path = os.path.expanduser(raw_path)
        if os.path.isabs(expanded_path):
            return os.path.abspath(expanded_path)

        return os.path.abspath(os.path.join(base_dir if base_dir is not None else os.getcwd(), expanded_path))

    def build_parent_path(self, path: str):
        current = os.path.abspath(os.path.expanduser(path))
        parent = os.path.dirname(current)
        if parent == current:
            return None
        return parent

    def to_abs_path(self, path: str) -> str:
        return os.path.abspath(os.path.expanduser(path))

    def is_file_path(self, path: str) -> bool:
        return os.path.isfile(os.path.expanduser(path))

    def get_current_directory(self) -> str:
        return os.getcwd()

    def require_existing_path(self, path: str) -> str:
        target_path = self.resolve_target_path(path)
        if not os.path.exists(target_path):
            raise FileNotFoundError(f'Path not found: {target_path}')
        return target_path

    def require_existing_non_empty_path(self, path: str) -> str:
        if not path or not path.strip():
            raise ValueError('Path is required')
        return self.require_existing_path(path)

    def require_existing_file(self, path: str) -> str:
        file_path = self.require_existing_path(path)
        if not os.path.isfile(file_path):
            raise IsADirectoryError(f'Not a file: {file_path}')
        return file_path

    def require_existing_directory(self, path: str) -> str:
        directory = self.resolve_target_path(path)
        if not os.path.exists(directory):
            raise FileNotFoundError(f'Directory not found: {directory}')
        if not os.path.isdir(directory):
            raise NotADirectoryError(f'Not a directory: {directory}')
        return directory

    # Text-command adapters decode their argument only at the command boundary.
    def require_existing_path_from_arg(self, raw) -> str:
        return self.require_existing_path(self.codec.extract_path(raw))

    def require_existing_non_empty_path_from_arg(self, raw) -> str:
        return self.require_existing_non_empty_path(self.codec.extract_path(raw))

    def require_existing_file_from_arg(self, raw) -> str:
        return self.require_existing_file(self.codec.extract_path(raw))

    def require_existing_directory_from_arg(self, raw) -> str:
        return self.require_existing_directory(self.codec.extract_path(raw))

    def require_existing_paths_from_list(self, paths) -> list[str]:
        resolved_paths = []

        for item in self._iter(paths):
            raw_path = ''
            if isinstance(item, dict):
                raw_path = (item.get('path') or '').strip()
            else:
                raw_path = str(item or '').strip()

            if not raw_path:
                continue

            target_path = self.resolve_target_path(raw_path)
            if not os.path.exists(target_path):
                raise FileNotFoundError(f'Path not found: {target_path}')

            resolved_paths.append(target_path)

        if not resolved_paths:
            raise ValueError('No valid paths provided')

        return resolved_paths