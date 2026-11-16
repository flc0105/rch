"""Schema-driven CLI tokenizer shared by ACMD argument rules and Server builtins.

Unlike a command router, this parses only a *declared* leaf's arguments. It
never guesses what a command or its flags mean from the command name.
"""
from core.commands.argument_errors import ArgumentCommandValidationError
from core.commands.argument_validator import ArgumentCommandValidator
from core.utils.parsing import split_shell_arguments


def _assignment_boundary(text: str) -> tuple[str, str]:
    """Keep an opaque assignment RHS; inline `--option=value` is not its delimiter."""
    quote = ''
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = ''
            continue
        if char in ("'", '"'):
            quote = char
            continue
        if char != '=':
            continue
        token_start = index
        while token_start and not text[token_start - 1].isspace():
            token_start -= 1
        if text[token_start:index].startswith('-'):
            continue  # --platform=mac and -p=mac are ordinary registered options.
        return text[:index], text[index:]
    return text, ''


def parse_argument_text(spec, text, *, literal_backslashes=False):
    """Return normalized option values; positional aliases share one spec.

    Flags have arity zero; other options take `arity` values. Repeated options
    preserve occurrence order. `--` stops option parsing for every schema.
    """
    raw_text = str(text or '')
    assignment = ''
    if spec.assignment_tail is not None:
        raw_text, assignment = _assignment_boundary(raw_text)
    try:
        tokens = split_shell_arguments(raw_text, literal_backslashes=literal_backslashes)
    except ValueError as exc:
        raise ArgumentCommandValidationError(f'Invalid arguments: {exc}') from exc

    try:
        if spec.trailing_named_arguments is not None:
            # The delimiter is owned by the shared CLI grammar. Everything
            # after it is a named business argument, never a builtin option.
            if '--' in tokens:
                boundary = tokens.index('--')
                head, tail = tokens[:boundary], tokens[boundary + 1:]
            else:
                head, tail = tokens, ()
            parsed = _parse_tokens(spec, head)
            parsed[spec.trailing_named_arguments] = _parse_named_tail(tail)
            return parsed
        parsed = _parse_tokens(spec, tokens)
        if spec.assignment_tail is not None:
            parsed[spec.assignment_tail] = assignment
        return parsed
    except ArgumentCommandValidationError as exc:
        # Error presentation is selected from declared flags by the caller,
        # not by retrying raw string parsing in every business handler.
        exc.seen_flags = _recognized_flags(spec, tokens)
        raise


def parse_partial_argument_tokens(spec, tokens):
    """Read completed and in-progress CLI arguments without required-value validation.

    Shares the execution parser's option names, aliases, and positional binding.
    The second result identifies options explicitly written with --name/-n.
    """
    return _parse_tokens(spec, tokens, partial=True)


def _parse_tokens(spec, tokens, *, partial=False):
    options = spec.get_option_map()
    aliases = spec.get_option_alias_map()
    raw = {}
    named = set()
    positionals = []
    idx = 0
    literal = False
    while idx < len(tokens):
        token = tokens[idx]
        if token == '--' and not literal:
            literal = True
            idx += 1
            continue
        if not literal and token.startswith('-') and token != '-' and not _negative_number(token):
            key, separator, inline = (token[2:] if token.startswith('--') else token[1:]).partition('=')
            opt = options.get(key) if token.startswith('--') else aliases.get(key)
            if opt is None and token.startswith('--'):
                opt = options.get(key.replace('-', '_'))
            if opt is None:
                raise ArgumentCommandValidationError(f'Unknown option: {token}')
            canonical = opt.name
            named.add(canonical)
            if canonical in raw and not opt.repeatable:
                raise ArgumentCommandValidationError(f'Duplicate option: --{canonical}')
            if opt.option_type == 'flag':
                if separator:
                    raise ArgumentCommandValidationError(f'Flag --{canonical} takes no value')
                value = True
                idx += 1
            else:
                count = opt.arity
                if count < 1:
                    raise ArgumentCommandValidationError(f'Invalid option arity: --{canonical}')
                values = ([inline] if separator else [])
                need = count - len(values)
                if len(tokens) - idx - 1 < need and partial:
                    break
                if len(tokens) - idx - 1 < need:
                    raise ArgumentCommandValidationError(f'Option --{canonical} requires {count} value(s)')
                values.extend(tokens[idx + 1:idx + 1 + need])
                value = values[0] if count == 1 else tuple(values)
                idx += 1 + need
            if opt.repeatable:
                raw.setdefault(canonical, []).append(value)
            else:
                raw[canonical] = value
            continue
        positionals.append(token)
        idx += 1

    positional_specs = sorted((opt for opt in spec.options if opt.is_positional),
                              key=lambda opt: opt.positional_index)
    available = [opt for opt in positional_specs if opt.name not in raw]
    if len(positionals) > len(available):
        raise ArgumentCommandValidationError(f'Too many positional arguments for {spec.name}')
    for opt, value in zip(available, positionals):
        raw[opt.name] = value
    return (raw, frozenset(named)) if partial else ArgumentCommandValidator().normalize(spec, raw)


def _negative_number(value):
    try:
        float(value)
        return value.startswith('-') and len(value) > 1
    except ValueError:
        return False


def _recognized_flags(spec, tokens):
    """Identify explicit flag occurrences while skipping values of other options."""
    options = spec.get_option_map()
    aliases = spec.get_option_alias_map()
    flags = set()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == '--':
            break
        if token.startswith('--'):
            key, marker, _ = token[2:].partition('=')
            opt = options.get(key) or options.get(key.replace('-', '_'))
        elif token.startswith('-'):
            key, marker, _ = token[1:].partition('=')
            opt = aliases.get(key)
        else:
            opt = None
            marker = ''
        if opt is not None:
            if opt.option_type == 'flag' and not marker:
                flags.add(opt.name)
            elif opt.option_type != 'flag':
                index += opt.arity - (1 if marker else 0)
        index += 1
    return frozenset(flags)


def _parse_named_tail(tokens):
    """Parse dynamic `--name value` pairs after an explicit `--` delimiter.

    The names belong to the receiving business schema; only the lexical
    syntax and duplicate checking are shared by Script and Job.
    """
    result = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith('--') or token == '--':
            raise ArgumentCommandValidationError(f'Expected named argument after --: {token}')
        key, separator, inline = token[2:].partition('=')
        if not key or key.startswith('-'):
            raise ArgumentCommandValidationError(f'Invalid named argument: {token}')
        if key in result:
            raise ArgumentCommandValidationError(f'Duplicate named argument: --{key}')
        if separator:
            value = inline
            index += 1
        else:
            if index + 1 >= len(tokens) or tokens[index + 1].startswith('--'):
                raise ArgumentCommandValidationError(f'Named argument --{key} requires a value')
            value = tokens[index + 1]
            index += 2
        result[key] = value
    return result
