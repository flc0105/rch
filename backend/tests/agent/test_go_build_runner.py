"""Go-only runner behavior and its two builder call sites."""

import importlib
import os
import subprocess
from pathlib import Path

import pytest

from server.application.agent.agent_go_build_runner import (
    GO_BUILD_TIMEOUT_SECONDS,
    GO_TARGET_MAP,
    GoBuildError,
    GoBuildResult,
    run_go_build,
)


def _completed(returncode=0, stdout='', stderr=''):
    return subprocess.CompletedProcess(['go', 'build'], returncode, stdout, stderr)


def test_go_runner_success_preserves_outputs_and_sets_build_environment(tmp_path, monkeypatch):
    output = tmp_path / 'executable'
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(command=cmd, **kwargs)
        output.write_bytes(b'go executable')
        return _completed(stdout='compiled ok\n', stderr='warning\n')

    monkeypatch.setattr(subprocess, 'run', fake_run)
    monkeypatch.setenv('GOOS', 'original')
    result = run_go_build(str(tmp_path), str(output), 'darwin', 'arm64')

    assert result == GoBuildResult(0, 'compiled ok\n', 'warning\n')
    assert captured['command'] == [
        'go', 'build', '-trimpath', '-ldflags', '-s -w', '-o', str(output), '.',
    ]
    assert captured['cwd'] == str(tmp_path)
    assert captured['capture_output'] is True
    assert captured['text'] is True
    assert captured['timeout'] == GO_BUILD_TIMEOUT_SECONDS
    assert captured['env']['CGO_ENABLED'] == '0'
    assert captured['env']['GOOS'] == 'darwin'
    assert captured['env']['GOARCH'] == 'arm64'
    assert os.environ['GOOS'] == 'original'
    assert output.stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize('returncode,stdout,stderr,expected', [
    (2, 'compiler stdout', 'compiler stderr', 'compiler stderr'),
    (1, 'compiler stdout', '', 'compiler stdout'),
    (3, '', '', 'no output'),
])
def test_go_runner_nonzero_exit_keeps_diagnostics(
    tmp_path, monkeypatch, returncode, stdout, stderr, expected,
):
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: _completed(returncode, stdout, stderr))
    with pytest.raises(GoBuildError, match=f'exit code {returncode}') as exc_info:
        run_go_build(str(tmp_path), str(tmp_path / 'output'), 'linux', 'amd64')
    result = exc_info.value.result
    assert result.exit_code == returncode
    assert result.stdout == stdout
    assert result.stderr == stderr
    assert result.timed_out is False
    assert expected in str(exc_info.value)


def test_go_runner_timeout_normalizes_partial_output(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        assert kwargs['timeout'] == 7
        raise subprocess.TimeoutExpired(cmd, 7, output=b'partial stdout \xff', stderr=b'partial stderr')

    monkeypatch.setattr(subprocess, 'run', fake_run)
    with pytest.raises(GoBuildError, match='timed out after 7s') as exc_info:
        run_go_build(str(tmp_path), str(tmp_path / 'output'), 'windows', 'amd64', timeout_seconds=7)
    assert exc_info.value.result == GoBuildResult(
        None, 'partial stdout \ufffd', 'partial stderr', True,
        'Go build timed out after 7s: partial stderr',
    )


def test_go_runner_missing_tool_returns_uniform_error(tmp_path, monkeypatch):
    def missing_go(*args, **kwargs):
        raise FileNotFoundError(2, 'No such file or directory', 'go')

    monkeypatch.setattr(subprocess, 'run', missing_go)
    with pytest.raises(GoBuildError, match='Go build could not start') as exc_info:
        run_go_build(str(tmp_path), str(tmp_path / 'output'), 'windows', 'amd64')
    assert exc_info.value.result.exit_code is None
    assert exc_info.value.result.stdout == ''
    assert exc_info.value.result.stderr == ''
    assert exc_info.value.result.timed_out is False


def test_go_runner_detects_missing_artifact_even_on_exit_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: _completed(0, 'success', ''))
    artifact = tmp_path / 'missing'
    with pytest.raises(GoBuildError, match='Build output not found') as exc_info:
        run_go_build(str(tmp_path), str(artifact), 'linux', 'amd64')
    assert exc_info.value.result.exit_code == 0
    assert exc_info.value.result.stdout == 'success'


def test_go_runner_windows_artifact_is_not_chmodded(tmp_path, monkeypatch):
    artifact = tmp_path / 'loader.exe'

    def fake_run(*args, **kwargs):
        artifact.write_bytes(b'fake')
        return _completed()

    def reject_chmod(*args, **kwargs):
        pytest.fail('Windows output must not use os.chmod')

    monkeypatch.setattr(subprocess, 'run', fake_run)
    monkeypatch.setattr(os, 'chmod', reject_chmod)
    assert run_go_build(str(tmp_path), str(artifact), 'windows', 'arm64').exit_code == 0


def test_go_runner_chmod_error_is_structured(tmp_path, monkeypatch):
    artifact = tmp_path / 'client'

    def fake_run(*args, **kwargs):
        artifact.write_bytes(b'fake')
        return _completed(0, 'done', '')

    def fail_chmod(*args, **kwargs):
        raise PermissionError('denied')

    monkeypatch.setattr(subprocess, 'run', fake_run)
    monkeypatch.setattr(os, 'chmod', fail_chmod)
    with pytest.raises(GoBuildError, match='permission update failed') as exc_info:
        run_go_build(str(tmp_path), str(artifact), 'linux', 'amd64')
    assert exc_info.value.result.exit_code == 0
    assert exc_info.value.result.stdout == 'done'


@pytest.mark.parametrize('module_name,builder_name,go_dir,expected_prefix', [
    ('agent_build_client_go', 'ClientGoBuilder', 'client-go', 'rchclient-go-client-'),
    ('agent_build_go_loader', 'GoLoaderBuilder', 'go-loader', 'rchclient-go-loader-'),
])
@pytest.mark.parametrize('target_os,goos,suffix', [
    ('win', 'windows', '.exe'),
    ('mac', 'darwin', ''),
    ('linux', 'linux', ''),
])
def test_both_go_builders_use_same_runner_and_platform_map(
    tmp_path, monkeypatch, module_name, builder_name, go_dir, expected_prefix,
    target_os, goos, suffix,
):
    module = importlib.import_module(f'server.application.agent.{module_name}')
    builder_class = getattr(module, builder_name)
    assert builder_class.GO_TARGET_MAP is GO_TARGET_MAP

    source_dir = tmp_path / 'source'
    config_dir = source_dir / go_dir / 'config'
    config_dir.mkdir(parents=True)
    (config_dir / 'config.go').write_text('package config\n', encoding='utf-8')
    work_dir = tmp_path / 'work'
    work_dir.mkdir()
    calls = []

    def fake_run(cwd, output_path, target_goos, goarch):
        calls.append((cwd, output_path, target_goos, goarch))
        Path(output_path).write_bytes(b'compiled binary')
        return GoBuildResult(0, 'ok', '')

    monkeypatch.setattr(module, 'run_go_build', fake_run)
    options = dict(
        work_dir=str(work_dir), server_host='localhost', server_port=9000,
        web_port=8085, target_os=target_os, target_arch='arm64',
        build_id='B123', build_version='test-123',
    )
    if go_dir == 'go-loader':
        options['listener_id'] = 'listener-abc'

    output = builder_class(str(source_dir)).build(**options)
    expected_name = f'{expected_prefix}{target_os}-arm64-B123{suffix}'
    expected_dir = work_dir / 'rat' / go_dir
    assert output == {
        'file_path': str(expected_dir / expected_name),
        'file_name': expected_name, 'warnings': ['Build completed.'],
        'target_arch': 'arm64', 'target_os': target_os,
    }
    assert calls == [(str(expected_dir), str(expected_dir / expected_name), goos, 'arm64')]
    config_text = (expected_dir / 'config' / 'config.go').read_text(encoding='utf-8')
    assert '8085' in config_text
    assert 'test-123' in config_text
    if go_dir == 'go-loader':
        assert 'const ServerListenerID = "listener-abc"' in config_text
