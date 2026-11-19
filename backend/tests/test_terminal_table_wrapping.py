"""Shared plain-text terminal table wrapping; unchanged structured JSON."""

import json

import pytest

from core.utils.command_output import StructuredCommandResult, render_structured_result
from core.utils.formatting import format_table, _cell_display_width


def test_short_table_is_unchanged():
    assert format_table(['name', 'ip', 'up'], [['en0', '192.168.2.1', 'yes']]) == (
        'name | ip          | up \n'
        '------------------------\n'
        'en0  | 192.168.2.1 | yes'
    )


def test_ios_many_ipv6_addresses_wrap_without_loss_and_keep_columns_aligned():
    ipv6 = ', '.join([
        'fe80::94:187b:138e:fc68%pdp_ip0',
        '240e:446:b5c:449c:4ee:d31d:82fa:c7e6',
        '240e:446:b5c:449c:1dd5:2409:cb65:5c1e',
    ])
    rows = [
        {'name': 'en0', 'ip': '192.168.2.232', 'ipv6': 'fe80::18f0:a3a1:883b:b3f2%en0', 'mac': '02:00:00:00:00:00', 'up': 'yes'},
        {'name': 'pdp_ip0', 'ip': '100.188.41.200', 'ipv6': ipv6, 'mac': '', 'up': 'yes'},
        {'name': 'pdp_ip1', 'ip': '', 'ipv6': '', 'mac': '', 'up': 'no'},
    ]
    text = format_table(list(rows[0]), [list(item.values()) for item in rows])
    lines = text.splitlines()
    assert len({_cell_display_width(line) for line in lines}) == 1
    assert _cell_display_width(lines[0].split(" | ")[2]) == 72
    assert lines[1].count('-') == len(lines[1])
    first = next(i for i, line in enumerate(lines) if line.startswith('pdp_ip0'))
    last = next(i for i, line in enumerate(lines) if line.startswith('pdp_ip1'))
    cells = [line.split(' | ') for line in lines[first:last]]
    assert len(cells) == 2
    assert ''.join(parts[2].rstrip() for parts in cells) == ipv6
    assert all(parts[0].strip() == '' for parts in cells[1:])
    assert 'pdp_ip1' in lines[last]


def test_explicit_lines_long_headers_and_full_width_characters():
    value = '中文界面真的很长：查看全部结果'
    text = format_table(['非常长的标题字段', 'msg'], [[value, 'first\nsecond']], max_cell_width=8)
    lines = text.splitlines()
    assert len({_cell_display_width(line) for line in lines}) == 1
    assert ''.join(line.split(' | ')[0].rstrip() for line in lines[3:]) == value
    assert 'second' in text
    assert all(_cell_display_width(line.split(' | ')[0]) == 8 for line in lines if ' | ' in line)


def test_invalid_width_and_invalid_rows_keep_expected_behavior():
    assert format_table([], []) == 'No headers to display'
    assert format_table(['x'], []) == 'No data to display'
    assert format_table(['x', 'y'], [['missing']]) == 'Table rows do not match header count'
    with pytest.raises(ValueError, match='max_cell_width'):
        format_table(['x'], [['y']], max_cell_width=0)


def test_structured_json_unaffected_by_table_wrap():
    payload = [{'name': 'pdp_ip0', 'ipv6': ', '.join(f'2001:db8::{i}' for i in range(12))}]
    result = StructuredCommandResult(status=1, data=payload, shape='table')
    assert json.loads(render_structured_result(result, output_format='json')[1]) == payload
    text = render_structured_result(result)[1]
    assert _cell_display_width(text.splitlines()[0].split(" | ")[1]) == 72
    assert len(text.splitlines()) > 3
