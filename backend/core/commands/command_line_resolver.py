from dataclasses import dataclass


@dataclass(frozen=True)
class CommandToken:
    """One shell-like token with decoded value and its original source span."""

    start: int
    end: int
    value: str
    raw: str


class CommandLineResolver:
    """Shared token and argument-position resolution for command entry points."""

    @staticmethod
    def normalize_cursor_units(value, text: str) -> int:
        try:
            cursor = int(value)
        except Exception:
            cursor = sum(2 if ord(char) > 0xFFFF else 1 for char in text)
        total = sum(2 if ord(char) > 0xFFFF else 1 for char in text)
        return max(0, min(cursor, total))

    @classmethod
    def normalize_cursor(cls, value, text: str) -> int:
        """Convert a browser UTF-16 selection offset to a Python string index."""
        cursor = cls.normalize_cursor_units(value, text)
        used = 0
        for index, char in enumerate(text):
            width = 2 if ord(char) > 0xFFFF else 1
            if used + width > cursor:
                return index
            used += width
        return len(text)

    @staticmethod
    def split_command(text: str) -> tuple[str, str]:
        """Split the first command word while preserving the remaining raw text."""
        source = str(text or '')
        for index, char in enumerate(source):
            if char.isspace():
                return source[:index].strip(), source[index + 1:]
        return source.strip(), ''

    @staticmethod
    def current_token(text: str) -> str:
        """Return the trailing whitespace-delimited fragment used by CompletionContext."""
        source = str(text or '')
        if not source:
            return ''
        parts = source.rsplit(maxsplit=1)
        if source[-1:].isspace():
            return ''
        return parts[-1] if parts else source

    @staticmethod
    def scan_tokens(text: str, *, max_tokens: int | None = None) -> list[CommandToken]:
        """Scan tokens while retaining source spans and shell quote/escape behavior."""
        source = str(text or '')
        tokens = []
        if max_tokens is not None and max_tokens <= 0:
            return tokens
        index = 0
        while index < len(source):
            while index < len(source) and source[index].isspace():
                index += 1
            if index >= len(source):
                break

            start = index
            quote = ''
            escaped = False
            value = []
            while index < len(source):
                char = source[index]
                if escaped:
                    value.append(char)
                    escaped = False
                    index += 1
                    continue
                if char == '\\' and quote != "'":
                    escaped = True
                    index += 1
                    continue
                if quote:
                    if char == quote:
                        quote = ''
                    else:
                        value.append(char)
                    index += 1
                    continue
                if char in ('"', "'"):
                    quote = char
                    index += 1
                    continue
                if char.isspace():
                    break
                value.append(char)
                index += 1

            end = index
            tokens.append(CommandToken(start, end, ''.join(value), source[start:end]))
            if max_tokens is not None and len(tokens) >= max_tokens:
                break
        return tokens

    @staticmethod
    def last_argument_span(text: str, cursor: int) -> tuple[int, int, str]:
        """Return the shell token at the cursor, including its suffix after the cursor."""
        source = str(text or '')
        cursor = max(0, min(int(cursor), len(source)))
        start = None
        quote = ''
        escaped = False
        for index, char in enumerate(source[:cursor]):
            if escaped:
                escaped = False
                continue
            if char == '\\' and quote != "'":
                if start is None:
                    start = index
                escaped = True
                continue
            if quote:
                if char == quote:
                    quote = ''
                continue
            if char in ('"', "'"):
                if start is None:
                    start = index
                quote = char
                continue
            if char.isspace():
                start = None
            elif start is None:
                start = index

        if start is None:
            return cursor, cursor, ''

        end = cursor
        for index in range(cursor, len(source)):
            char = source[index]
            if escaped:
                escaped = False
                end = index + 1
                continue
            if char == '\\' and quote != "'":
                escaped = True
                end = index + 1
                continue
            if quote:
                if char == quote:
                    quote = ''
                end = index + 1
                continue
            if char in ('"', "'"):
                quote = char
                end = index + 1
                continue
            if char.isspace():
                break
            end = index + 1
        return start, end, source[start:end]

    @classmethod
    def command_tail_span(cls, text: str, cursor: int) -> tuple[int, int, str]:
        """Return everything after the first command token, skipping its separator."""
        source = str(text or '')
        cursor = max(0, min(int(cursor), len(source)))
        tokens = cls.scan_tokens(source[:cursor], max_tokens=1)
        if not tokens:
            return cursor, cursor, ''
        start = tokens[0].end
        while start < cursor and source[start].isspace():
            start += 1
        if start == tokens[0].end and start >= cursor:
            return cursor, cursor, ''
        return start, len(source), source[start:]

    @classmethod
    def resolve_completion_argument(cls, raw_input: str, cursor: int,
                                    tokens: list[CommandToken], argument_spec,
                                    *, command_token_count: int):
        """Locate the declared CompletionSpec for the active ACMD argument."""
        if any(token.value == '--' for token in tokens[command_token_count:]):
            return None
        options = list(argument_spec.options or [])
        option_map = {'--' + item.name: item for item in options}
        alias_map = {'-' + item.alias: item for item in options if item.alias}
        active = tokens[-1] if tokens else None
        prefix = str(raw_input or '')[:cursor]

        if active is not None and not prefix.endswith((' ', '\t')) and active.value.startswith('--') and '=' in active.value:
            option_name, _ = active.value.split('=', 1)
            option = option_map.get(option_name)
            if option and option.completion:
                _, active_end, _ = cls.last_argument_span(raw_input, cursor)
                value_start = active.start + len(option_name) + 1
                return option.completion, (
                    value_start, active_end, str(raw_input or '')[value_start:active_end]
                )
            return None

        if active is not None and len(tokens) >= 2 and not prefix.endswith((' ', '\t')):
            previous = tokens[-2].value
            option = option_map.get(previous) or alias_map.get(previous)
            if option and not option.is_flag:
                return (option.completion, cls.last_argument_span(raw_input, cursor)) if option.completion else None

        if prefix.endswith((' ', '\t')) and active is not None:
            option = option_map.get(active.value) or alias_map.get(active.value)
            if option:
                return (option.completion, (cursor, cursor, '')) if not option.is_flag and option.completion else None
            if active.value.startswith('-'):
                return None

        if (active is not None and not prefix.endswith((' ', '\t'))
                and active.value.startswith('-')):
            return None

        positional = []
        filled_positions = set()
        index = command_token_count
        while index < len(tokens):
            token = tokens[index].value
            option = None
            has_inline_value = False
            if token.startswith('--'):
                option_name, separator, _ = token.partition('=')
                option = option_map.get(option_name)
                has_inline_value = bool(separator)
            elif token.startswith('-') and len(token) == 2:
                option = alias_map.get(token)

            if option is not None:
                if not option.is_flag:
                    if has_inline_value:
                        if option.positional_index is not None:
                            filled_positions.add(option.positional_index)
                    elif index + 1 < len(tokens):
                        if option.positional_index is not None:
                            filled_positions.add(option.positional_index)
                        index += 2
                        continue
                index += 1
                continue
            if token.startswith('-'):
                index += 1
                continue
            positional.append(tokens[index])
            index += 1

        # Named options can satisfy positional arguments as well. Once --name
        # has a value, subsequent words must not request that name again.
        available_positions = sorted(item.positional_index for item in options
                                     if item.positional_index is not None
                                     and item.positional_index not in filled_positions)
        active_positional = len(positional) if prefix.endswith((' ', '\t')) else max(0, len(positional) - 1)
        if active_positional >= len(available_positions):
            return None
        current_index = available_positions[active_positional]
        current_span = (cursor, cursor, '') if prefix.endswith((' ', '\t')) else cls.last_argument_span(raw_input, cursor)
        for option in options:
            if option.positional_index == current_index and option.completion:
                return option.completion, current_span
        return None
