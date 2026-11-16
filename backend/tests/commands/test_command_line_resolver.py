from core.command_completion.models import CompletionSpec
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.commands.command_line_resolver import CommandLineResolver


def _completion_spec():
    return CompletionSpec('filesystem', ('file', 'directory'))


def _argument_spec():
    return ArgumentCommandSpec('image_info', options=[
        ArgumentOptionSpec('path', positional_index=0, completion=_completion_spec()),
        ArgumentOptionSpec('db', alias='d', completion=_completion_spec()),
        ArgumentOptionSpec('format'),
        ArgumentOptionSpec('verbose', option_type='flag', alias='v'),
    ])


def _resolve(text, cursor=None):
    resolver = CommandLineResolver()
    cursor = len(text) if cursor is None else cursor
    tokens = resolver.scan_tokens(text[:cursor])
    return resolver.resolve_completion_argument(
        text, cursor, tokens, _argument_spec(), command_token_count=2,
    )


def test_scan_tokens_keeps_decoded_values_and_original_spans():
    text = 'acmd image_info --path="/tmp/a b" escaped\\ name \'quoted value\''
    tokens = CommandLineResolver.scan_tokens(text)

    assert [token.value for token in tokens] == [
        'acmd', 'image_info', '--path=/tmp/a b', 'escaped name', 'quoted value',
    ]
    assert [text[token.start:token.end] for token in tokens] == [token.raw for token in tokens]
    assert tokens[2].raw == '--path="/tmp/a b"'
    assert tokens[3].raw == r'escaped\ name'
    assert CommandLineResolver.scan_tokens(text, max_tokens=2) == tokens[:2]


def test_last_argument_span_replaces_the_whole_quoted_or_mid_cursor_token():
    text = 'acmd image_info --db="/tmp/a b.txt" --format json'
    start, end, value = CommandLineResolver.last_argument_span(text, text.index('a b') + 1)
    assert value == '--db="/tmp/a b.txt"'
    assert text[start:end] == value

    text = 'acmd image_info --db=/tmp/file'
    cursor = text.index('/tmp/fi') + len('/tmp/fi')
    start, end, value = CommandLineResolver.last_argument_span(text, cursor)
    assert value == '--db=/tmp/file'
    assert text[start:end] == value


def test_command_tail_span_preserves_the_complete_path_argument():
    text = '  cd   "/Users/Test Folder"/Doc'
    cursor = text.index('Doc') + 2
    assert CommandLineResolver.command_tail_span(text, cursor) == (
        7, len(text), '"/Users/Test Folder"/Doc',
    )


def test_cursor_conversion_uses_browser_utf16_offsets():
    assert CommandLineResolver.normalize_cursor_units(6, 'cd 😀/folder') == 6
    assert CommandLineResolver.normalize_cursor(6, 'cd 😀/folder') == 5


def test_positional_completion_skips_named_option_values_and_flags():
    text = 'acmd image_info --format png -v /tmp/image'
    completion, span = _resolve(text)
    assert completion == _completion_spec()
    assert span == (len('acmd image_info --format png -v '), len(text), '/tmp/image')


def test_named_option_completion_supports_separate_and_inline_values():
    text = 'acmd image_info --db /tmp/index.sqlite'
    completion, span = _resolve(text)
    assert completion == _completion_spec()
    assert span == (text.index('/tmp/index.sqlite'), len(text), '/tmp/index.sqlite')

    text = 'acmd image_info -d /tmp/index.sqlite'
    completion, span = _resolve(text)
    assert completion == _completion_spec()
    assert span[2] == '/tmp/index.sqlite'

    text = 'acmd image_info --db=/tmp/index.sqlite'
    completion, span = _resolve(text)
    assert completion == _completion_spec()
    assert span[2] == '/tmp/index.sqlite'


def test_named_option_completion_resolves_empty_value_after_separator():
    text = 'acmd image_info --db '
    completion, span = _resolve(text)
    assert completion == _completion_spec()
    assert span == (len(text), len(text), '')


def test_completion_span_keeps_suffix_when_cursor_is_inside_inline_value():
    text = 'acmd image_info --db=/tmp/index.sqlite --format json'
    cursor = text.index('/tmp/in') + len('/tmp/in')
    completion, span = _resolve(text, cursor)
    assert completion == _completion_spec()
    assert span == (
        text.index('/tmp/index.sqlite'),
        text.index(' --format'),
        '/tmp/index.sqlite',
    )
