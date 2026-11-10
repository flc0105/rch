"""Canonical agent builder identities and generated artifact naming."""
from enum import Enum


class AgentBuilderKind(str, Enum):
    PYTHON = 'python'
    GO = 'go'
    GO_LOADER = 'go_loader'


AGENT_BUILDER_LABELS = {
    AgentBuilderKind.PYTHON: 'Python Bundle',
    AgentBuilderKind.GO: 'Go',
    AgentBuilderKind.GO_LOADER: 'Go Loader',
}


def agent_build_version(builder, build_id: str) -> str:
    return f'{AgentBuilderKind(builder).value}_{build_id}'


def agent_output_filename(builder, build_id: str, *, target_os='', target_arch='', suffix='') -> str:
    kind = AgentBuilderKind(builder)
    stem = kind.value
    if kind != AgentBuilderKind.PYTHON:
        if not target_os or not target_arch:
            raise ValueError('Executable output requires OS and architecture')
        stem = f'{stem}_{target_os}_{target_arch}'
    return f'{stem}_{build_id}{suffix}'
