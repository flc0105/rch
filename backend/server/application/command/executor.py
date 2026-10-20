from functools import partial
import re

from core.utils.parsing import parse
from server.application.command.builtin_command_handler import BuiltinCommandHandler
from server.application.command.command_planner import CommandPlanner
from server.application.execution.remote_execution_service import RemoteExecutionService
from server.application.command.command_types import COMMAND_TYPE_COMMAND
from server.application.tasks.task_types import TASK_TYPE_COMMAND

class CommandExecutor:
    def __init__(
        self,
        conn,
        server,
        remote_execution_service=None,
        planner=None,
        use_foreground_guard: bool = False,
        foreground_source: str = 'cli'
    ):
        self.conn = conn
        self.server = server
        self.current_history_entry_id = ''
        self.remote_execution_service = remote_execution_service or RemoteExecutionService(server)
        self.use_foreground_guard = bool(use_foreground_guard)
        self.foreground_source = (foreground_source or '').strip() or 'cli'

        self.planner = planner or CommandPlanner(
            alias_manager=server.alias_manager,
            plan_executor=self._execute_remote_plan,
            error_executor=self._yield_error,
            conn=self.conn,
            alias_resolved_callback=self._on_alias_resolved,
        )

        self.builtin_handler = BuiltinCommandHandler(
            conn=self.conn,
            server=self.server,
            plan_builder=self.planner,
            remote_execution_service=self.remote_execution_service,
            history_entry_id_provider=self._get_current_history_entry_id,
            plan_executor_factory=self._create_plan_executor,
            command_processor_factory=self._create_nested_command_processor,
        )

    def _get_current_history_entry_id(self) -> str:
        return self.current_history_entry_id


    def _on_alias_resolved(self, alias_plan: dict):
        resolved_command = str(alias_plan.get('command') or '').strip()
        alias_name = str(alias_plan.get('alias_name') or '').strip()
        alias_platform = str(alias_plan.get('alias_platform') or '').strip()

        # alias 现在保留用户原始输入，不再把 history entry 改写为展开后的真实命令。
        if resolved_command:
            platform_suffix = f' [{alias_platform}]' if alias_platform else ''
            yield 1, f'alias {alias_name}{platform_suffix} -> {resolved_command}'

    def _yield_error(self, error):
        yield 0, str(error)

    def _create_plan_executor(self):
        return self._execute_remote_plan

    def _create_nested_command_processor(self):
        def processor(cmd: str):
            return self.process_command(cmd, history_entry_id=self.current_history_entry_id)
        return processor

    def _execute_remote_plan(self, plan: dict):
        history = getattr(self.server, 'command_history_orchestrator', None)
        if history is not None:
            history.describe_plan(self.current_history_entry_id, plan)
        if self.use_foreground_guard:
            return partial(
                self.remote_execution_service.stream_foreground_command,
                self.conn,
                plan.get('command', ''),
                command_type=plan.get('command_type', COMMAND_TYPE_COMMAND),
                extra=plan.get('extra'),
                history_entry_id=self.current_history_entry_id,
                task_type=TASK_TYPE_COMMAND,
                source=self.foreground_source,
            )

        return partial(
            self.remote_execution_service.stream_command,
            self.conn,
            plan.get('command', ''),
            command_type=plan.get('command_type', COMMAND_TYPE_COMMAND),
            extra=plan.get('extra'),
            history_entry_id=self.current_history_entry_id
        )

    def get_command_candidates(self):
        return self.builtin_handler.get_command_candidates()

    def _resolve_builtin_command(self, name, arg):
        try:
            builtin_iter = self.builtin_handler.resolve_builtin_command(name, arg)
            if builtin_iter is None:
                return None
            return partial(lambda it: it, builtin_iter)
        except Exception as e:
            return partial(self._yield_error, e)

    def _rewrite_history_shortcut(self, cmd: str) -> str:
        """
        将 !<index> 改写为正式 builtin: history run <index>

        这里故意只保留很薄的一层语法糖，不在 executor 里做真正的历史解析。
        真正的 quick history 查找、提示输出、以及继续执行，统一交给 history builtin。
        """
        command_text = (cmd or '').strip()
        matched = re.fullmatch(r'!(\d+)', command_text)
        if matched is None:
            return command_text

        history_index = matched.group(1)
        return f'history run {history_index}'


    def process_command(self, cmd, history_entry_id: str = ''):
        self.current_history_entry_id = (history_entry_id or '').strip()

        normalized_command = self._rewrite_history_shortcut(cmd)
        name, arg = parse(normalized_command)

        builtin_handler = self._resolve_builtin_command(name, arg)
        if builtin_handler:
            return builtin_handler

        return self.planner.resolve(normalized_command, name, arg)
