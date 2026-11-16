from core.command_completion.models import CompletionContext
from core.commands.command_line_resolver import CommandLineResolver


class CommandCompletionParser:
    """
    将 command bar 原始输入解析成补全上下文。
    """

    def parse(self, raw_input: str = '', cursor_position: int | None = None, max_results: int = 50, metadata: dict | None = None) -> CompletionContext:
        text = str(raw_input or '')
        cursor = CommandLineResolver.normalize_cursor(cursor_position, text)
        scoped_text = text[:cursor]
        left_trimmed_text = scoped_text.lstrip()
        leading_trim_count = len(scoped_text) - len(left_trimmed_text)

        if not left_trimmed_text:
            return CompletionContext(
                raw_input=text,
                cursor_position=cursor,
                max_results=max_results,
                metadata=dict(metadata or {}),
            )

        command_name, argument_text = CommandLineResolver.split_command(left_trimmed_text)
        current_token = CommandLineResolver.current_token(argument_text)
        return CompletionContext(
            raw_input=text,
            command_name=command_name.lower(),
            argument_text=argument_text,
            current_token=current_token,
            cursor_position=max(cursor - leading_trim_count, 0),
            max_results=max_results,
            metadata=dict(metadata or {}),
        )

