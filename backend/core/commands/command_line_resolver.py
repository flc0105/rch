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
        if len(tokens) <= command_token_count and not prefix.endswith((' ', '\t')):
            return None

        if active is not None and not prefix.endswith((' ', '\t')) and active.value.startswith('-') and '=' in active.value:
            option_name, _ = active.value.split('=', 1)
            option = option_map.get(option_name) or alias_map.get(option_name)
            if option is None and option_name.startswith('--'):
                option = option_map.get('--' + option_name[2:].replace('-', '_'))
            if option and option.completion:
                _, active_end, _ = cls.last_argument_span(raw_input, cursor)
                value_start = active.start + len(option_name) + 1
                return option.completion, (
                    value_start, active_end, str(raw_input or '')[value_start:active_end]
                )
            return None

        if active is not None and len(tokens) >= 2 and not prefix.endswith((' ', '\t')):
            previous = tokens[-2].value
            option = (option_map.get(previous) or alias_map.get(previous) or
                      (option_map.get('--' + previous[2:].replace('-', '_')) if previous.startswith('--') else None))
            if option and not option.is_flag:
                return (option.completion, cls.last_argument_span(raw_input, cursor)) if option.completion else None

        if prefix.endswith((' ', '\t')) and active is not None:
            option = (option_map.get(active.value) or alias_map.get(active.value) or
                      (option_map.get('--' + active.value[2:].replace('-', '_')) if active.value.startswith('--') else None))
            if option:
                return (option.completion, (cursor, cursor, '')) if not option.is_flag and option.completion else None
            if active.value.startswith('-'):
                return None

        if (active is not None and not prefix.endswith((' ', '\t'))
                and active.value.startswith('-')):
            return None

        # Use the execution argument grammar for the completed tokens. The
        # current unfinished token is excluded so it does not consume its slot.
        from core.commands.argument_parser import parse_partial_argument_tokens
        from core.commands.argument_errors import ArgumentCommandValidationError
        completed = tokens[command_token_count:] if prefix.endswith((' ', '\t')) else tokens[command_token_count:-1]
        try:
            filled, _ = parse_partial_argument_tokens(argument_spec, [token.value for token in completed])
        except ArgumentCommandValidationError:
            return None
        available = sorted((item for item in options
                            if item.is_positional and item.name not in filled),
                           key=lambda item: item.positional_index)
        if not available or not available[0].completion:
            return None
        span = ((cursor, cursor, '') if prefix.endswith((' ', '\t'))
                else cls.last_argument_span(raw_input, cursor))
        return available[0].completion, span
