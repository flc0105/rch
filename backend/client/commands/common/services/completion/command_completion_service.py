import re

from core.command_completion.models import CompletionCandidate, CompletionContext, CompletionSpec
from core.command_completion.parser import CommandCompletionParser


class FileSystemCompletionProvider:
    """Enumerate one Client directory and filter entries by CompletionSpec.kinds."""

    name = 'filesystem'

    def __init__(self, path_resolver, file_system_service):
        self.path_resolver = path_resolver
        self.file_system_service = file_system_service

    def complete(self, raw_input: str, cursor_position: int, spec: CompletionSpec,
                 *, argument_span=None) -> list[CompletionCandidate]:
        text = str(raw_input or '')
        cursor = max(0, min(int(cursor_position), len(text)))
        start, end, raw_path = argument_span or _last_argument_span(text, cursor)
        path_value = _unquote_path(raw_path)
        lookup_path, candidate_prefix = _split_path(path_value)
        directory = self.path_resolver.require_existing_directory_from_arg(lookup_path)
        payload = self.file_system_service.list_child_paths(directory)
        entries = payload.get('entries') if isinstance(payload, dict) else []
        allowed = set(spec.kinds)
        result = []
        for item in _sort_entries(entries):
            if not isinstance(item, dict):
                continue
            is_dir = bool(item.get('is_dir'))
            kind = 'directory' if is_dir else 'file'
            if allowed and kind not in allowed:
                continue
            name = str(item.get('name') or '').strip()
            if not name:
                continue
            candidate_path = f'{candidate_prefix}{name}'
            replacement = _quote_replacement(candidate_path, raw_path)
            insert_text = text[:start] + replacement + text[end:]
            path = str(item.get('path') or candidate_path)
            result.append(CompletionCandidate(
                title=insert_text,
                insert_text=insert_text,
                description=path,
                source='client_filesystem',
                group='filesystem',
                kind=kind,
                name=name,
                priority=10 if is_dir else 20,
                metadata={
                    'path': path,
                    'candidatePath': candidate_path,
                    'lookupPath': lookup_path,
                    'isDir': is_dir,
                },
            ))
        return result


def _sort_entries(entries):
    return sorted(
        (item for item in (entries or []) if isinstance(item, dict)),
        key=lambda item: (
            not bool(item.get('is_dir')),
            str(item.get('name') or '').casefold(),
            str(item.get('name') or ''),
        ),
    )


def _split_path(path: str) -> tuple[str, str]:
    text = str(path or '').strip()
    separator = max(text.rfind('/'), text.rfind('\\'))
    if separator < 0:
        return '', ''
    if separator == len(text) - 1:
        return text, text
    if separator == 2 and len(text) >= 2 and text[1] == ':':
        return text[:separator + 1], text[:separator + 1]
    if separator == 0:
        return text[:1], text[:1]
    return text[:separator], text[:separator + 1]


def _first_command(text: str) -> str:
    return str(text or '').lstrip().split(maxsplit=1)[0].lower() if str(text or '').strip() else ''


def _command_tail_span(text: str, cursor: int) -> tuple[int, int, str]:
    prefix = str(text or '')[:cursor]
    match = re.match(r'^\s*\S+\s+', prefix)
    if not match:
        return cursor, cursor, ''
    start = match.end()
    while start < cursor and text[start].isspace():
        start += 1
    return start, len(text), text[start:]


def _last_argument_span(text: str, cursor: int) -> tuple[int, int, str]:
    """Return the shell token at cursor, or an empty token after trailing whitespace."""
    prefix = text[:cursor]
    start = len(prefix)
    quote = ''
    escaped = False
    for index in range(len(prefix) - 1, -1, -1):
        char = prefix[index]
        if escaped:
            escaped = False
            continue
        if char == '\\' and quote != "'":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = ''
            continue
        if char in ('"', "'"):
            quote = char
            continue
        if char.isspace():
            start = index + 1
            break
        start = index
    if prefix and prefix[-1:].isspace():
        start = cursor
    end = cursor
    # Keep the rest of the same token when the cursor is in its middle.
    quote = ''
    escaped = False
    for index in range(cursor, len(text)):
        char = text[index]
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
    return start, end, text[start:end]


def _unquote_path(value: str) -> str:
    text = str(value or '').strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1]
    if text.startswith('"'):
        text = text[1:]
    return re.sub(r'\\(["\\$`])', r'\1', text)


def _quote_replacement(candidate: str, original: str) -> str:
    text = str(original or '')
    if text.startswith('"'):
        encoded = candidate.replace('\\', '\\\\').replace('"', '\\"')
        return '"' + encoded + ('"' if text.endswith('"') and len(text) > 1 else '')
    if text.startswith("'"):
        encoded = candidate.replace("'", "'\\''")
        return "'" + encoded + ("'" if text.endswith("'") and len(text) > 1 else '')
    return candidate


class ClientCommandCompletionService:
    """Resolve the local command/ACMD declaration and run its registered provider."""

    def __init__(self, command_host):
        self.command_host = command_host
        self.parser = CommandCompletionParser()
        self.providers = {
            'filesystem': FileSystemCompletionProvider(
                path_resolver=command_host.path_resolver,
                file_system_service=command_host.file_system_service,
            ),
        }

    def complete(self, payload: dict) -> dict:
        data = payload if isinstance(payload, dict) else {}
        raw_input = str(data.get('raw_input') or '')
        cursor_units = _coerce_cursor_units(data.get('cursor_position'), raw_input)
        cursor = _coerce_cursor(cursor_units, raw_input)
        context = self.parser.parse(
            raw_input=raw_input,
            cursor_position=cursor_units,
            max_results=_coerce_limit(data.get('max_results')),
        )
        declaration = self._resolve_declaration(raw_input, cursor, data.get('completion'))
        if declaration is None:
            items = []
        else:
            spec, span = declaration
            provider = self.providers.get(spec.provider)
            items = provider.complete(raw_input, cursor, spec, argument_span=span) if provider else []
        limit = _coerce_limit(data.get('max_results'))
        if limit > 0:
            items = items[:limit]
        return {
            'context': context.to_dict(),
            'items': [item.to_dict() for item in items],
        }

    def _resolve_declaration(self, raw_input: str, cursor: int, override):
        if isinstance(override, dict):
            spec = CompletionSpec.from_dict(override)
            command = _first_command(raw_input[:cursor])
            span = _command_tail_span(raw_input, cursor) if command in ('edit', 'cd', 'download') else _last_argument_span(raw_input, cursor)
            return spec, span

        prefix = raw_input[:cursor]
        tokens = _scan_tokens(prefix)
        if not tokens:
            return None
        command = tokens[0][2].lower()
        if command == 'acmd':
            if len(tokens) < 2:
                return None
            command_name = tokens[1][2].lower()
            registry = self.command_host.get_argument_command_registry()
            entry = getattr(registry, '_entries', {}).get(command_name) if registry else None
            spec = entry.get('spec') if isinstance(entry, dict) else None
            if spec is None:
                return None
            return self._resolve_acmd_argument(raw_input, cursor, tokens, spec)

        commands = self.command_host
        method = getattr(commands, command, None)
        completion = getattr(method, 'command_completion', None)
        if completion is None:
            return None
        # Shell-like path commands consume the remainder as one path argument.
        span = _command_tail_span(raw_input, cursor)
        return completion, span

    def _resolve_acmd_argument(self, raw_input, cursor, tokens, argument_spec):
        options = list(argument_spec.options or [])
        option_map = {'--' + item.name: item for item in options}
        alias_map = {'-' + item.alias: item for item in options if item.alias}
        active = tokens[-1] if tokens else None

        # A --name=value token puts the cursor inside the value portion.
        if active is not None and active[2].startswith('--') and '=' in active[2]:
            option_name, _ = active[2].split('=', 1)
            option = option_map.get(option_name)
            if option and option.completion:
                _, active_end, _ = _last_argument_span(raw_input, cursor)
                value_start = active[0] + len(option_name) + 1
                return option.completion, (value_start, active_end, raw_input[value_start:active_end])

        # The active value belongs to the immediately preceding named option.
        if active is not None and len(tokens) >= 2 and not raw_input[:cursor].endswith((' ', '\t')):
            previous = tokens[-2][2]
            option = option_map.get(previous) or alias_map.get(previous)
            if option and not option.is_flag and option.completion:
                start, end, value = _last_argument_span(raw_input, cursor)
                return option.completion, (start, end, value)

        # If the user just typed a value-taking option and a trailing space,
        # the empty token after it is the option's value.
        if raw_input[:cursor].endswith((' ', '\t')) and active is not None:
            option = option_map.get(active[2]) or alias_map.get(active[2])
            if option and not option.is_flag and option.completion:
                return option.completion, (cursor, cursor, '')

        # Resolve annotated positional parameters, skipping named option values.
        positional = []
        index = 2
        while index < len(tokens):
            token = tokens[index][2]
            if token.startswith('--'):
                if '=' not in token:
                    option = option_map.get(token)
                    if option and not option.is_flag:
                        index += 2
                        continue
                index += 1
                continue
            if token.startswith('-') and len(token) == 2:
                option = alias_map.get(token)
                if option and not option.is_flag:
                    index += 2
                    continue
                index += 1
                continue
            positional.append(tokens[index])
            index += 1
        current_index = len(positional) - 1 if positional else 0
        current_span = _last_argument_span(raw_input, cursor) if active else (cursor, cursor, '')
        if raw_input[:cursor].endswith((' ', '\t')):
            current_span = (cursor, cursor, '')
            current_index = len(positional)
        for option in options:
            if option.positional_index == current_index and option.completion:
                return option.completion, current_span
        return None


def _scan_tokens(text):
    tokens = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        start = index
        quote = ''
        escaped = False
        value = []
        while index < len(text):
            char = text[index]
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
        tokens.append((start, end, ''.join(value)))
    return tokens


def _coerce_cursor_units(value, text):
    try:
        cursor = int(value)
    except Exception:
        cursor = sum(2 if ord(char) > 0xFFFF else 1 for char in text)
    total = sum(2 if ord(char) > 0xFFFF else 1 for char in text)
    return max(0, min(cursor, total))


def _coerce_cursor(value, text):
    # Browser selectionStart and the Web API use UTF-16 code units.
    cursor = _coerce_cursor_units(value, text)
    used = 0
    for index, char in enumerate(text):
        width = 2 if ord(char) > 0xFFFF else 1
        if used + width > cursor:
            return index
        used += width
    return len(text)


def _coerce_limit(value):
    try:
        limit = int(value)
    except Exception:
        limit = 50
    return max(0, min(limit, 200))
