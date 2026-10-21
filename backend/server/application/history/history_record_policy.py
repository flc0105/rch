"""Activity eligibility: dispatch-confirmed execution, never text blacklists.

A non-empty command is only a *candidate*. The orchestrator persists an
Activity only after an explicit candidate has actually been sent to Client.
Internal module calls (file browsing, jobs, process polling, upload) do not
create Activity candidates in this first release.
"""
class CommandHistoryRecordPolicy:
    NON_RECORD_TASK_TYPES = frozenset({'upload', 'remote_file', 'process', 'job_control', 'external_tool'})
    RECORD_SOURCES = frozenset({'web', 'web_terminal', 'web_api', 'quick_action', 'cli'})

    @staticmethod
    def is_internal_external_tool_command(command):
        """Internal Client lifecycle RPCs aren't user commands."""
        first = str(command or '').strip().split(None, 1)
        return bool(first) and first[0].lower().startswith('external_tool_')

    @staticmethod
    def is_xt_query(command):
        """Read-only xt subcommands are excluded from Activity only."""
        parts = str(command or '').strip().split(None, 2)
        if not parts or parts[0].lower() != 'xt':
            return False
        return len(parts) == 1 or (parts[1].lower() in {
            'list', 'info', 'which', 'help', '-h', '--help', '--json',
        })

    @classmethod
    def should_record_command(cls, command, *, source='', task_type=''):
        return (bool(str(command or '').strip())
                and not cls.is_internal_external_tool_command(command)
                and not cls.is_xt_query(command)
                and str(task_type or '').strip().lower() not in cls.NON_RECORD_TASK_TYPES
                and source in cls.RECORD_SOURCES)
