import re

from core.protocol.structured_arg_codec import JSON_PREFIX


class CommandHistoryRecordPolicy:
    """
    统一命令历史记录策略。

    为什么放在这里：
    - 仅靠注解无法覆盖全部场景：有些命令是 server builtin，有些是 client command，
      还有一些是 web/job/file/process 层动态拼出来的字符串命令。
    - 这里作为单一规则源，统一决定：某条命令是否进入 history。

    当前规则（如需继续扩展，优先改这里）：
    - 纯 history 元命令不记录：history / history clear
    - history replay 记录，但最终 command 保留为被回放的真实命令：history run <index> / !<index>
    - 所有 __json__: payload 结构命令不记录
    - web 高频操作命令不记录：remote file / process / job control / web upload / run_script
    - job 相关命令默认不记录
    - alias / gopin 这类用户输入快捷命令保留原始输入，不在这里改写
    """

    JSON_PAYLOAD_PREFIX = JSON_PREFIX

    HISTORY_REPLAY_PATTERN = re.compile(r'^(?:history\s+run\s+\d+|!\d+)$', re.IGNORECASE)
    HISTORY_META_PATTERN = re.compile(r'^history(?:\s+clear)?$', re.IGNORECASE)

    JSON_STYLE_COMMAND_NAMES = {
        'run_script',
        'browse_dir',
        'create_dir',
        'rename_path',
        'delete_path',
        'delete_paths',
        'paste_paths',
        'preview_path',
        'save_file_content',
        'download_path',
        'download_paths',
        'receive_http_upload',
    }

    PROCESS_COMMAND_NAMES = {
        'list_processes',
        'get_process_detail',
        'kill_process',
        'list_apps',
    }

    JOB_COMMAND_NAMES = {
        'start_job',
        'jobs',
        'jobs_ps',
        'stop_job',
        'stop_all_jobs',
    }

    NON_RECORD_TASK_TYPES = {
        'upload',
        'remote_file',
        'process',
        'job_control',
    }

    @classmethod
    def _normalize_command(cls, command: str) -> str:
        return str(command or '').strip()

    @classmethod
    def _split_command(cls, command: str) -> tuple[str, str]:
        text = cls._normalize_command(command)
        if not text:
            return '', ''
        parts = text.split(None, 1)
        name = parts[0].strip().lower()
        arg_text = parts[1].strip() if len(parts) > 1 else ''
        return name, arg_text

    @classmethod
    def is_history_replay_command(cls, command: str) -> bool:
        return cls.HISTORY_REPLAY_PATTERN.fullmatch(cls._normalize_command(command)) is not None

    @classmethod
    def is_history_meta_command(cls, command: str) -> bool:
        text = cls._normalize_command(command)
        if not text:
            return False
        if cls.is_history_replay_command(text):
            return False
        return cls.HISTORY_META_PATTERN.fullmatch(text) is not None

    @classmethod
    def has_json_payload_arg(cls, command: str) -> bool:
        _, arg_text = cls._split_command(command)
        return arg_text.startswith(cls.JSON_PAYLOAD_PREFIX)

    @classmethod
    def should_record_command(cls, command: str, *, source: str = '', task_type: str = '') -> bool:
        command_text = cls._normalize_command(command)
        if not command_text:
            return False

        normalized_source = str(source or '').strip().lower()
        normalized_task_type = str(task_type or '').strip().lower()
        name, _ = cls._split_command(command_text)

        if cls.is_history_replay_command(command_text):
            return True

        if cls.is_history_meta_command(command_text):
            return False

        if normalized_task_type in cls.NON_RECORD_TASK_TYPES:
            return False

        if cls.has_json_payload_arg(command_text):
            return False

        if name in cls.JSON_STYLE_COMMAND_NAMES:
            return False

        if name in cls.PROCESS_COMMAND_NAMES:
            return False

        if name in cls.JOB_COMMAND_NAMES:
            return False

        if name == 'run_script':
            return False

        return True
