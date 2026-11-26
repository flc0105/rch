"""Result-level view validation and Python package presentation."""
from types import SimpleNamespace

import pytest

from client.commands.acmd.registry import ArgumentCommandRegistry
from client.commands.acmd.standalone import python_packages as packages
from core.protocol.result_envelope import build_result_wire_event, result_wire_event
from core.utils.command_output import project_result_output_texts


def registry_for(*handlers):
    registry = ArgumentCommandRegistry(SimpleNamespace(command_platform='linux'))
    for handler in handlers:
        registry.register(handler)
    return registry


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
