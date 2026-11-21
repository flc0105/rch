"""Result-level JSON Viewer metadata, probe command and distribution lists."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from client.commands.acmd.registry import ArgumentCommandRegistry
from client.commands.acmd.standalone.view_probe import view_probe
from client.commands.acmd.standalone.ps import ps
from client.commands.acmd.standalone import python_packages as packages
from core.protocol.result_envelope import build_result_wire_event, result_wire_event
from core.utils.command_output import project_result_output_texts


def registry_for(*handlers):
    registry = ArgumentCommandRegistry(SimpleNamespace(command_platform='linux'))
    for handler in handlers:
        registry.register(handler)
    return registry


def execute(registry, **args):
    return registry.execute({'name': 'view_probe', 'args': args})


def test_probe_raw_data_and_single_table_action_templates():
    registry = registry_for(view_probe)
    execute(registry, reset=True)
    status, result = execute(registry, f='json')
    assert status == 1
    assert result['status'] == 'success'
    assert len(result['data']) == 3
    assert result['presentation']['requested'] == 'json'
    assert all('_actions' not in row for row in result['data'])
    assert result['view']['titleField'] == 'name'
    assert result['view']['columns'][0] == {'field': 'id', 'width': 90}
    assert result['view']['details'] == ['owner', 'note']
    assert len(result['view']['actions']) == 4
    assert result['view']['actions'][0]['refresh'] is True
    assert result['view']['actions'][1]['confirm'] is False
    wire = result_wire_event(100, status, result)
    assert wire['view'] == result['view']
    assert wire['data'] == result['data']
    assert project_result_output_texts([wire]) == [project_result_output_texts([result])[0]]


def test_probe_real_delete_mark_reset_and_error_do_not_modify_system():
    registry = registry_for(view_probe)
    execute(registry, reset=True)
    status, message = execute(registry, delete=102)
    assert status == 1 and 'Deleted probe row 102' in message
    status, result = execute(registry, json=True)
    assert status == 1 and len(result['data']) == 2
    assert not any(row['id'] == 102 for row in result['data'])
    assert execute(registry, delete=102)[0] == 0
    assert execute(registry, mark=101)[0] == 1
    assert execute(registry, inspect=101)[1]['data']['state'] == 'marked'
    assert execute(registry, reset=True)[0] == 1
    assert len(execute(registry, json=True)[1]['data']) == 3
    assert 'actions' not in execute(registry, json=True, plain=True)[1]['view']


def test_wire_rejects_malformed_or_oversized_view():
    base = {'event_type': 'completed', 'status': 'success', 'data': [{'id': 1}]}
    with pytest.raises(ValueError, match='view column size'):
        build_result_wire_event(1, {**base, 'view': {'columns': [{'field': 'id', 'width': -10}]}})
    with pytest.raises(ValueError, match='view action flag'):
        build_result_wire_event(1, {**base, 'view': {'actions': [{'label': 'X', 'command': 'getpid', 'refresh': 'yes'}]}})
    with pytest.raises(ValueError, match='too large'):
        build_result_wire_event(1, {**base, 'view': {'actions': [{'label': 'X', 'command': 'x' * 17000}]}})


def test_distribution_lists_same_identity_lines_only_drops_version_from_display(monkeypatch):
    distributions = [SimpleNamespace(metadata={'Name': name}, version=version)
                     for name, version in [('Pillow', '10.2'), ('psutil', '5.0')]]
    monkeypatch.setattr(packages.metadata, 'distributions', lambda: distributions)
    monkeypatch.setattr(packages.metadata, 'packages_distributions', lambda: {'PIL': ['Pillow'], 'psutil': ['psutil']})
    monkeypatch.setattr(packages.metadata, 'distribution', lambda name: next(
        item for item in distributions if item.metadata['Name'].lower() == name.lower()))
    monkeypatch.setattr(packages.sys, 'modules', {'PIL': object(), 'psutil': object()})
    reg = registry_for(packages.python_packages)
    status, default = reg.execute({'name': 'python_packages', 'args': {}})
    assert status == 1 and default['presentation']['default'] == 'lines'
    assert default['data'] == [{'package': 'Pillow', 'version': '10.2'}, {'package': 'psutil', 'version': '5.0'}]
    assert '10.2' not in project_result_output_texts([default])[0]
    status, loaded = reg.execute({'name': 'python_packages', 'args': {'l': True, 'f': 'table'}})
    assert status == 1 and loaded['data'] == default['data']
    assert '10.2' in project_result_output_texts([loaded])[0]
    status, filtered = reg.execute({'name': 'python_packages', 'args': {'l': True, 'filter': 'pillow'}})
    assert status == 1 and [x['package'] for x in filtered['data']] == ['Pillow']
    assert reg.execute({'name': 'python_packages', 'args': {'n': 'PIL'}})[0] == 0
