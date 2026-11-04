"""Small, Go-only build subprocess runner shared by the two Go builders."""

import os
import subprocess
from dataclasses import dataclass
from typing import Optional


GO_TARGET_MAP = {
    'win': {'GOOS': 'windows', 'suffix': '.exe', 'label': 'windows'},
    'mac': {'GOOS': 'darwin', 'suffix': '', 'label': 'mac'},
    'linux': {'GOOS': 'linux', 'suffix': '', 'label': 'linux'},
}
GO_BUILD_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class GoBuildResult:
    exit_code: Optional[int]
    stdout: str
    stderr: str
    timed_out: bool = False
    error: str = ''


class GoBuildError(RuntimeError):
    def __init__(self, result: GoBuildResult):
        super().__init__(result.error)
        self.result = result


def _output_text(value) -> str:
    # TimeoutExpired can contain bytes even when subprocess.run(text=True).
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return value or ''


def run_go_build(cwd: str, output_path: str, goos: str, goarch: str,
                 timeout_seconds: int = GO_BUILD_TIMEOUT_SECONDS) -> GoBuildResult:
    """Compile one Go binary, returning captured output or raising GoBuildError."""
    env = os.environ.copy()
    env.update({'CGO_ENABLED': '0', 'GOOS': goos, 'GOARCH': goarch})
    cmd = ['go', 'build', '-trimpath', '-ldflags', '-s -w', '-o', output_path, '.']
    try:
        completed = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace',
            env=env, timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        result = GoBuildResult(
            exit_code=None, stdout=_output_text(exc.stdout), stderr=_output_text(exc.stderr),
            timed_out=True, error=f'Go build timed out after {timeout_seconds}s: '
                                  f'{_output_text(exc.stderr) or _output_text(exc.stdout) or "no output"}',
        )
        raise GoBuildError(result) from exc
    except OSError as exc:
        raise GoBuildError(GoBuildResult(None, '', '', error=f'Go build could not start: {exc}')) from exc

    result = GoBuildResult(completed.returncode, completed.stdout or '', completed.stderr or '')
    if result.exit_code != 0:
        raise GoBuildError(GoBuildResult(
            result.exit_code, result.stdout, result.stderr,
            error=f'Go build failed (exit code {result.exit_code}): '
                  f'{result.stderr or result.stdout or "no output"}',
        ))
    if not os.path.isfile(output_path):
        raise GoBuildError(GoBuildResult(
            result.exit_code, result.stdout, result.stderr,
            error=f'Build output not found: {output_path}',
        ))
    if goos != 'windows':
        try:
            os.chmod(output_path, 0o755)
        except OSError as exc:
            raise GoBuildError(GoBuildResult(
                result.exit_code, result.stdout, result.stderr,
                error=f'Go build output permission update failed: {exc}',
            )) from exc
    return result
