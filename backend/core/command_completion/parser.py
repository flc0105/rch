from core.command_completion.models import CompletionContext


class CommandCompletionParser:
    """
    将 command bar 原始输入解析成补全上下文。
    """

    def parse(self, raw_input: str = '', cursor_position: int | None = None, max_results: int = 50, metadata: dict | None = None) -> CompletionContext:
        text = str(raw_input or '')
        cursor = self._normalize_cursor(cursor_position, text)
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

        command_name, argument_text = self._split_command(left_trimmed_text)
        return CompletionContext(
            raw_input=text,
            command_name=command_name.lower(),
            argument_text=argument_text,
            current_token=self._extract_current_token(argument_text),
            cursor_position=max(cursor - leading_trim_count, 0),
            max_results=max_results,
            metadata=dict(metadata or {}),
        )

    def _normalize_cursor(self, cursor_position: int | None, text: str) -> int:
        try:
            cursor = int(cursor_position)
        except Exception:
            cursor = sum(2 if ord(char) > 0xFFFF else 1 for char in text)
        cursor = max(0, cursor)
        used = 0
        for index, char in enumerate(text):
            width = 2 if ord(char) > 0xFFFF else 1
            if used + width > cursor:
                return index
            used += width
        return len(text)

    def _split_command(self, text: str) -> tuple[str, str]:
        command_chars = []
        for index, char in enumerate(text):
            if char.isspace():
                return ''.join(command_chars).strip(), text[index + 1:]
            command_chars.append(char)
        return ''.join(command_chars).strip(), ''

    def _extract_current_token(self, argument_text: str) -> str:
        text = str(argument_text or '')
        if not text:
            return ''

        # command bar 当前只补末尾 token；引号内复杂语法后续可替换为 shlex lexer。
        parts = text.rsplit(maxsplit=1)
        if text[-1:].isspace():
            return ''
        return parts[-1] if parts else text
