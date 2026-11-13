import pytest

from core.utils.script_metadata import read_script_metadata_from_source, rewrite_script_metadata_name


@pytest.mark.parametrize('metadata_key', ['SCRIPT_METADATA', 'metadata'])
def test_rename_changes_only_top_level_name(metadata_key):
    source = (f'{metadata_key} = {{"display_name": "中文", "name": "old/path",\r\n'
              '    "params": [{"name": "old/path", "type": "string"}], # preserve comment\r\n'
              '}\r\nprint("old/path")\r\n')
    actual = rewrite_script_metadata_name(source, 'new/脚本')
    assert actual == source.replace('"name": "old/path"', '"name": "new/脚本"', 1)
    assert read_script_metadata_from_source(actual)['name'] == 'new/脚本'


def test_metadata_name_missing_or_nonliteral_source_remains_unchanged():
    for source in ('print("hello")', 'SCRIPT_METADATA = {"display_name": "Hello"}',
                   'SCRIPT_METADATA = make_metadata()', 'def broken('):
        assert rewrite_script_metadata_name(source, 'new/name') == source


def test_multiline_metadata_name():
    source = 'SCRIPT_METADATA = {"name": ("old/"\n "name"), "display_name": "Old"}\n'
    actual = rewrite_script_metadata_name(source, 'new/name')
    assert read_script_metadata_from_source(actual)['name'] == 'new/name'
    assert '"display_name": "Old"' in actual
