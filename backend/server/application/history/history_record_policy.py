"""Activity eligibility: dispatch-confirmed execution, never text blacklists.

A non-empty command is only a *candidate*. The orchestrator persists an
Activity only after an explicit candidate has actually been sent to Client.
Internal module calls (file browsing, jobs, process polling, upload) do not
create Activity candidates in this first release.
"""
import re


class CommandHistoryRecordPolicy:
    NON_RECORD_TASK_TYPES = frozenset({'upload', 'remote_file', 'process', 'job_control', 'external_tool'})
    RECORD_SOURCES = frozenset({'web', 'web_terminal', 'web_api', 'quick_action', 'cli'})
    _REPLAY_PATTERN = re.compile(r'(?:history\s+run\s+\d+|!\d+)', re.IGNORECASE)

    @classmethod
    def is_history_replay_command(cls, command_text):
        """Exclude replay meta commands from Quick's executable index list."""
        return bool(cls._REPLAY_PATTERN.fullmatch(str(command_text or '').strip()))

    @classmethod
    def should_record_command(cls, command, *, source='', task_type=''):
        return (bool(str(command or '').strip())
                and str(task_type or '').strip().lower() not in cls.NON_RECORD_TASK_TYPES
                and source in cls.RECORD_SOURCES)
