"""Shell screenshot command: common upload flow with platform capture functions."""

import os
import shlex
import subprocess

from client.commands.shell.decorators import shell_command
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.runtime.temp_workspace import make_client_temp_file, cleanup_temp_path
from core.utils.artifact_naming import build_artifact_filename


def _capture_mac(owner, path):
    """Capture using the managed subprocess for cancellation and cleanup."""
    command = f'screencapture -x {shlex.quote(path)}'
    result = owner.process_execution_service.run_shell_command(command)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or 'Failed to capture screenshot')


def _capture_win(owner, path):
    import pyautogui

    pyautogui.screenshot().save(path)


@shell_command('Capture a screenshot', group='media', output='stream',
               platforms=('mac', 'win'))
def screenshot(self):
    """Capture the local screen and upload the PNG as a Saved screenshot."""
    screenshot_path = ''
    try:
        fd, screenshot_path = make_client_temp_file(
            'media_temp', prefix='screenshot_', suffix='.png',
        )
        os.close(fd)
        self.emit_progress(f'Client Temp Path: {screenshot_path}', level='info')
        self.emit_progress('Capturing screen...', level='info')

        # Platform availability is enforced by @shell_command in the Shell runner.
        capture = {'mac': _capture_mac, 'win': _capture_win}[self.command_platform]
        capture(self, screenshot_path)

        self.emit_progress('Screenshot captured successfully', level='success')
        return self.http_file_transfer_service.upload_single_file_to_server_result(
            screenshot_path,
            category='screenshots', managed=True,
            upload_name=build_artifact_filename('screenshot', 'png'),
            extra={'saved_from': 'client_command', 'source_command': 'screenshot'},
        )
    except CommandCancelledError:
        raise
    except (CommandTimeoutError, subprocess.TimeoutExpired):
        return 0, 'Screenshot capture timed out and was terminated'
    except Exception as exc:
        return 0, f'Failed to capture screenshot: {exc}'
    finally:
        if screenshot_path:
            cleanup_temp_path(screenshot_path)
