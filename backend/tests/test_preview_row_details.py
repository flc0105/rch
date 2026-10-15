"""Opt-in table row details; no changes to plain Previews or Cleanup selection."""
import runpy
from pathlib import Path

import pytest

from server.application.execution.interaction_broker import InteractionBroker
from client.runtime.sdk import context


def _plan():
    return {
        'columns': [{'key': 'name', 'label': 'Name'}],
        'rows': [{'name': 'Alpha'}, {'name': 'Beta'}],
        'row_ids': ['a', 'b'],
        'row_details': [{'row_id': 'b', 'content': 'file-1\nfile-2'}],
        'details': [{'title': 'Scan warnings', 'content': 'Some paths unavailable'}],
    }


def test_row_details_are_opt_in_and_preserve_original_schema():
    preview = InteractionBroker._normalize_preview(_plan())
    assert preview['row_details'] == [{'row_id': 'b', 'content': 'file-1\nfile-2'}]
    assert preview['row_ids'] == ['a', 'b']
    assert preview['details'] == [{'title': 'Scan warnings', 'content': 'Some paths unavailable'}]
    original = dict(_plan())
    original.pop('row_details')
    assert 'row_details' not in InteractionBroker._normalize_preview(original)
    original.pop('row_ids')
    assert 'row_ids' not in InteractionBroker._normalize_preview(original)


@pytest.mark.parametrize('row_details', [
    {}, 'hello', [{'row_id': 'unknown', 'content': 'x'}],
    [{'row_id': 'b', 'content': 'x'}, {'row_id': 'b', 'content': 'y'}],
    [{'row_id': 'b', 'content': 'x', 'html': '<img>'}],
    [{'row_id': 'b', 'content': 42}],
    [{'row_id': 'b', 'content': 'x' * 4001}],
    [{'row_id': 1, 'content': 'x'}],
    [{'row_id': 'a', 'content': 'x'}, {'row_id': 'b', 'content': 'y'},
     {'row_id': 'c', 'content': 'z'}],
])
def test_invalid_row_details_rejected(row_details):
    with pytest.raises(ValueError, match='row detail|row_details|Preview text'):
        InteractionBroker._normalize_preview({**_plan(), 'row_details': row_details})


def test_row_details_require_selection_ids():
    plan = _plan()
    plan.pop('row_ids')
    with pytest.raises(ValueError, match='row_details'):
        InteractionBroker._normalize_preview(plan)


def test_cleanup_row_details_bound_to_selected_plan(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    script = root / 'server/resources/scripts/mac/maintenance/personal_cleanup.py'
    assert script.is_file()
    # Loading definitions must not run the user's destructive cleanup.
    namespace = runpy.run_path(str(script), run_name='test_only')
    first = tmp_path / 'first'
    second = tmp_path / 'second'
    first.mkdir()
    second.mkdir()
    (first / 'one.txt').write_text('one')
    (second / 'two.txt').write_text('two')
    (second / 'deep').mkdir()
    (second / 'deep' / 'three.log').write_text('three')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(context, 'progress', lambda *a, **kw: None)
    entries = [{'path': str(first), 'enabled': True},
               {'path': str(second), 'enabled': True}]
    inspected = []

    def choose(message, preview, **kwargs):
        inspected.append(preview)
        clean = InteractionBroker._normalize_preview(preview)
        assert clean['row_ids'] == ['1', '2']
        details = {d['row_id']: d['content'] for d in clean['row_details']}
        assert 'one.txt' in details['1']
        assert 'two.txt' in details['2'] and 'deep/three.log' in details['2']
        assert clean['columns'][0] == {'key': 'label', 'label': 'Name'}
        assert all(d['title'] != 'Files: first' for d in clean['details'])
        assert (first / 'one.txt').exists() and (second / 'two.txt').exists()
        return ['2']

    monkeypatch.setattr(context, 'select_preview_rows', choose)
    result = namespace['main']({'cleanup_paths': entries})
    assert len(inspected) == 1
    assert result['approved'] is True
    assert result['removed_files_and_links'] == 2
    assert (first / 'one.txt').is_file()
    assert not (second / 'two.txt').exists()
    assert not (second / 'deep').exists()
    assert second.is_dir()


def test_cleanup_zero_rows_selected_changes_nothing(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / 'server/resources/scripts/mac/maintenance/personal_cleanup.py'
    namespace = runpy.run_path(str(script), run_name='test_only')
    target = tmp_path / 'target'
    target.mkdir()
    (target / 'stay.txt').write_text('stay')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(context, 'progress', lambda *a, **kw: None)
    monkeypatch.setattr(context, 'select_preview_rows', lambda *args, **kwargs: [])
    result = namespace['main']({'cleanup_paths': [{'path': str(target), 'enabled': True}]})
    assert result['reason'] == 'no selected targets'
    assert (target / 'stay.txt').exists()
