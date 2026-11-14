from core.command_completion.models import CompletionCandidate, CompletionContext
from core.command_completion.provider import CommandCompletionProvider


class FileSystemChildPathCommandCompletionProvider(CommandCompletionProvider):
    """
    client 文件系统子项补全基类。
    """

    source = 'client_filesystem'
    group = 'filesystem'
    entry_kind = 'path'
    command_names: tuple[str, ...] = ()

    def __init__(self, path_resolver, file_system_service):
        self.path_resolver = path_resolver
        self.file_system_service = file_system_service

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        path_parts = self._split_path_argument(context.argument_text)
        lookup_path = path_parts['lookup_path']
        candidate_prefix = path_parts['candidate_prefix']

        directory = self.path_resolver.require_existing_directory_from_arg(lookup_path)
        payload = self.list_entries(directory)
        entries = payload.get('entries') if isinstance(payload, dict) else []
        sorted_entries = self.sort_filesystem_entries(entries)

        result = []
        for item in sorted_entries:
            if not isinstance(item, dict):
                continue

            name = str(item.get('name') or '').strip()
            path = str(item.get('path') or '').strip()
            if not name:
                continue

            candidate_path = self.normalize_candidate_path(f'{candidate_prefix}{name}', item)
            insert_text = self.build_insert_text(candidate_path, item)
            entry_kind = self.resolve_entry_kind(item)
            result.append(CompletionCandidate(
                title=insert_text,
                insert_text=insert_text,
                description=self.build_description(path or candidate_path, item),
                source=self.source,
                group=self.group,
                kind=entry_kind,
                name=name,
                priority=self.resolve_candidate_priority(item),
                metadata={
                    'path': path,
                    'candidatePath': candidate_path,
                    'lookupPath': lookup_path,
                    'isDir': bool(item.get('is_dir')),
                },
            ))

        return result

    def list_entries(self, directory: str) -> dict:
        raise NotImplementedError

    def sort_filesystem_entries(self, entries) -> list[dict]:
        # filesystem completion 统一排序：目录在前、文件在后，各自按名称字母序。
        valid_entries = [item for item in (entries or []) if isinstance(item, dict)]
        return sorted(
            valid_entries,
            key=lambda item: (
                not bool(item.get('is_dir')),
                str(item.get('name') or '').casefold(),
                str(item.get('name') or ''),
            ),
        )

    def normalize_candidate_path(self, candidate_path: str, item: dict) -> str:
        return candidate_path

    def build_insert_text(self, candidate_path: str, item: dict | None = None) -> str:
        raise NotImplementedError

    def resolve_entry_kind(self, item: dict) -> str:
        return self.entry_kind

    def resolve_candidate_priority(self, item: dict) -> int:
        # Registry 会按 priority 再按 title 排序；filesystem provider 用 priority 固化目录优先级。
        return 10 if bool((item or {}).get('is_dir')) else 20

    def build_description(self, path: str, item: dict | None = None) -> str:
        return path

    def _split_path_argument(self, argument_text: str) -> dict:
        text = str(argument_text or '').strip()
        if not text:
            return {
                'lookup_path': '',
                'candidate_prefix': '',
            }

        last_forward_slash_index = text.rfind('/')
        last_backward_slash_index = text.rfind('\\')
        last_separator_index = max(last_forward_slash_index, last_backward_slash_index)

        if last_separator_index < 0:
            return {
                'lookup_path': '',
                'candidate_prefix': '',
            }

        if last_separator_index == len(text) - 1:
            return {
                # 输入 a/b/ 时，候选子项应来自 a/b。
                'lookup_path': text,
                'candidate_prefix': text,
            }

        return {
            # 输入 a/bc 时，候选子项应来自 a，并用 bc 做前端本地过滤。
            'lookup_path': self._build_lookup_path_before_last_separator(text, last_separator_index),
            'candidate_prefix': text[:last_separator_index + 1],
        }

    def _build_lookup_path_before_last_separator(self, text: str, last_separator_index: int) -> str:
        if last_separator_index <= 0:
            return text[:last_separator_index + 1]

        # Windows 盘符根目录：C:\foo 应查询 C:\。
        if last_separator_index == 2 and len(text) >= 2 and text[1] == ':':
            return text[:last_separator_index + 1]

        return text[:last_separator_index]


class CdDirectoryCommandCompletionProvider(FileSystemChildPathCommandCompletionProvider):
    """
    client cd 命令目录补全。
    """

    command_names = ('cd',)
    source = 'client_cd'
    entry_kind = 'directory'

    def list_entries(self, directory: str) -> dict:
        return self.file_system_service.list_child_directories(directory)

    def build_insert_text(self, candidate_path: str, item: dict | None = None) -> str:
        return f'cd {candidate_path}'.strip()

    def build_description(self, path: str, item: dict | None = None) -> str:
        return f'Change directory -> {path}'


class DownloadPathCommandCompletionProvider(FileSystemChildPathCommandCompletionProvider):
    """
    client download 命令路径补全，同时返回目录和文件。
    """

    command_names = ('download',)
    source = 'client_download'
    entry_kind = 'path'

    def list_entries(self, directory: str) -> dict:
        return self.file_system_service.list_child_paths(directory)

    def normalize_candidate_path(self, candidate_path: str, item: dict) -> str:
        # download 与 cd 的展示保持一致：目录候选不额外追加 /。
        # 如需继续进入目录，用户继续输入 / 后再触发下一层补全。
        return candidate_path

    def build_insert_text(self, candidate_path: str, item: dict | None = None) -> str:
        return f'download {candidate_path}'.strip()

    def resolve_entry_kind(self, item: dict) -> str:
        return 'directory' if bool(item.get('is_dir')) else 'file'

    def build_description(self, path: str, item: dict | None = None) -> str:
        if bool((item or {}).get('is_dir')):
            return f'Enter directory -> {path}'
        return f'Download file -> {path}'


class EditPathCommandCompletionProvider(DownloadPathCommandCompletionProvider):
    """Remote text-file editor path completion for the local RCHCLI command."""

    command_names = ('edit',)
    source = 'client_edit'

    def build_insert_text(self, candidate_path: str, item: dict | None = None) -> str:
        return f'edit {candidate_path}'.strip()

    def build_description(self, path: str, item: dict | None = None) -> str:
        if bool((item or {}).get('is_dir')):
            return f'Enter directory -> {path}'
        return f'Edit file -> {path}'


