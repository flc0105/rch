"""Script catalog extraction must not flood Server logs with user-code warnings."""

import warnings

from core.utils.script_metadata import read_script_metadata_from_source


def test_invalid_escape_during_metadata_scan_does_not_warn():
    source = "SCRIPT_METADATA = {'name': 'win-tool'}\n" + "path = 'C:\\\\windows\\system32\\cmd.exe'\n"
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter('always')
        for _ in range(12):
            metadata = read_script_metadata_from_source(source)
            assert metadata['name'] == 'win-tool'
    assert not [item for item in captured if issubclass(item.category, SyntaxWarning)]


def test_metadata_scan_still_rejects_syntax_errors():
    assert read_script_metadata_from_source("SCRIPT_METADATA = {broken") == {}
