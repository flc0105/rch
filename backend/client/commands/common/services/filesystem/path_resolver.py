import os

from core.protocol.structured_arg_codec import StructuredArgCodec


class PathResolver:
    """
    路径解析与存在性校验服务。
    """

    def __init__(self, codec: StructuredArgCodec | None = None, iter_interruptible=None):
        self.codec = codec or StructuredArgCodec()
        self.iter_interruptible = iter_interruptible

    def _iter(self, iterable, check_interval: int = 1):
        if self.iter_interruptible is None:
            return iterable
        return self.iter_interruptible(iterable, check_interval=check_interval)

    def validate_directory_exists(self, path):
        directory = os.path.abspath(path)
        if not os.path.isdir(directory):
            raise FileNotFoundError(f'Directory not found: {directory}')
        return directory

    def validate_file_exists(self, path):
        file_path = os.path.abspath(path)
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f'File not found: {file_path}')
        return file_path

    def resolve_target_path(self, path: str) -> str:
        raw_path = (path or '').strip()
        # 空路径保留“当前工作目录”语义，供浏览等非破坏性命令使用。
        if not raw_path:
            raw_path = '.'

        if os.path.isabs(raw_path):
            return os.path.abspath(raw_path)

        return os.path.abspath(os.path.join(os.getcwd(), raw_path))

    def build_parent_path(self, path: str):
        current = os.path.abspath(path)
        parent = os.path.dirname(current)
        if parent == current:
            return None
        return parent

    def to_abs_path(self, path: str) -> str:
        return os.path.abspath(path)

    def is_file_path(self, path: str) -> bool:
        return os.path.isfile(path)

    def get_current_directory(self) -> str:
        return os.getcwd()

    def require_existing_path_from_arg(self, raw) -> str:
        target_path = self.resolve_target_path(self.codec.extract_path(raw))
        if not os.path.exists(target_path):
            raise FileNotFoundError(f'Path not found: {target_path}')
        return target_path

    def require_existing_non_empty_path_from_arg(self, raw) -> str:
        raw_path = self.codec.extract_path(raw)
        if not raw_path:
            raise ValueError('Path is required')
        return self.require_existing_path_from_arg(raw_path)

    def require_existing_file_from_arg(self, raw) -> str:
        file_path = self.require_existing_path_from_arg(raw)
        if not os.path.isfile(file_path):
            raise IsADirectoryError(f'Not a file: {file_path}')
        return file_path

    def require_existing_directory_from_arg(self, raw) -> str:
        directory = self.resolve_target_path(self.codec.extract_path(raw))
        if not os.path.exists(directory):
            raise FileNotFoundError(f'Directory not found: {directory}')
        if not os.path.isdir(directory):
            raise NotADirectoryError(f'Not a directory: {directory}')
        return directory

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