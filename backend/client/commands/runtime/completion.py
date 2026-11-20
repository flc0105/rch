import re

from core.command_completion.models import CompletionCandidate, CompletionContext, CompletionSpec
from core.command_completion.parser import CommandCompletionParser
from core.command_completion.registry import CommandCompletionRegistry
from core.commands.command_line_resolver import CommandLineResolver


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
        start, end, raw_path = argument_span or CommandLineResolver.last_argument_span(text, cursor)
        path_value = _unquote_path(raw_path)
        lookup_path, candidate_prefix = _split_path(path_value)
        # Match the typed name before the caller caps results; otherwise a
        # large directory can hide every matching entry past the first page.
        name_prefix = path_value[len(candidate_prefix):]
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
            if not name or not name.startswith(name_prefix):
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

    def __init__(self, catalog):
        self.catalog = catalog
        command_host = catalog.get_commands()
        self.parser = CommandCompletionParser()
        self.resolver = CommandLineResolver()
        self.providers = CommandCompletionRegistry({
            'filesystem': FileSystemCompletionProvider(
                path_resolver=command_host.path_resolver,
                file_system_service=command_host.file_system_service,
            ),
        })

    def complete(self, payload: dict) -> dict:
        data = payload if isinstance(payload, dict) else {}
        raw_input = str(data.get('raw_input') or '')
        cursor_units = self.resolver.normalize_cursor_units(data.get('cursor_position'), raw_input)
        cursor = self.resolver.normalize_cursor(cursor_units, raw_input)
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
            tokens = self.resolver.scan_tokens(raw_input[:cursor])
            command = tokens[0].raw.lower() if tokens else ''
            span = (self.resolver.command_tail_span(raw_input, cursor)
                    if command in ('edit', 'cd', 'download')
                    else self.resolver.last_argument_span(raw_input, cursor))
            return spec, span

        prefix = raw_input[:cursor]
        tokens = self.resolver.scan_tokens(prefix)
        if not tokens:
            return None
        command = tokens[0].value.lower()
        if command == 'acmd':
            if len(tokens) < 2:
                return None
            command_name = tokens[1].value.lower()
            registry = self.catalog.get_argument_command_registry()
            entry = getattr(registry, '_entries', {}).get(command_name) if registry else None
            spec = entry.get('spec') if isinstance(entry, dict) else None
            if spec is None:
                return None
            return self.resolver.resolve_completion_argument(
                raw_input, cursor, tokens, spec, command_token_count=2,
            )

        method = self.catalog.get_shell_command(command)
        completion = getattr(method, 'command_completion', None)
        if completion is None:
            return None
        # Shell-like path commands consume the remainder as one path argument.
        span = self.resolver.command_tail_span(raw_input, cursor)
        return completion, span


def _coerce_limit(value):
    try:
        limit = int(value)
    except Exception:
        limit = 50
    return max(0, min(limit, 200))
