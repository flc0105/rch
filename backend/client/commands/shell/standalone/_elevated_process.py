"""Read process results after an adapter obtains native OS authorization."""

import base64
import codecs
import json
import os
import subprocess
import time

from core.utils.local_process_channel import MAX_FRAME_BYTES, accept_peer, open_listener, read_frame


ELEVATED_COMMAND_TIMEOUT = 150


class ElevationCancelled(OSError):
    """The OS authorization prompt was cancelled."""


def run_authorized_process(owner, platform, mode, command, *, startup_log=None, clear_env=()):
    """Launch the detached Windows Client for spawn_elevated_instance."""
    from client.commands.shell.standalone._elevated_win import WindowsElevation

    if (platform, mode) != ('win', 'detached'):
        raise ValueError('The elevated Client launcher requires Windows detached mode')
    return WindowsElevation(owner).detached(command, startup_log=startup_log, clear_env=clear_env)


def run_tracked(owner, launch, mode, command, *, encoding='utf-8', collect=False,
                startup_log=None, clear_env=()):
    deadline = time.monotonic() + ELEVATED_COMMAND_TIMEOUT

    def checkpoint():
        owner._checkpoint()
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired('run_elevated', ELEVATED_COMMAND_TIMEOUT)

    cwd = os.getcwd()
    emit = owner.emit_chunk if mode == 'shell' and not collect else None
    with open_listener() as (listener, endpoint):
        request = {**endpoint, 'mode': mode, 'command': command, 'cwd': cwd}
        if startup_log is not None:
            request.update(startup_log=startup_log, clear_env=clear_env)
        payload = base64.b64encode(json.dumps(request, ensure_ascii=False).encode('utf-8')).decode('ascii')
        with launch(payload, cwd) as error_if_exited:
            with accept_peer(listener, endpoint, checkpoint, error_if_exited) as peer:
                return _read_result(peer, checkpoint, mode, emit, encoding, collect)


def _read_result(peer, checkpoint, mode, emit, encoding, collect):
    decoder = codecs.getincrementaldecoder(encoding)(errors='replace')
    pending = ''
    collected = []

    while True:
        kind, data = read_frame(peer, checkpoint)
        if kind == b'E':
            raise OSError(data.decode('utf-8', errors='replace').strip())
        if kind == b'P' and mode == 'detached':
            return 1, f'Elevated process started (PID: {int(data)})'
        if kind == b'O' and mode == 'shell':
            output = decoder.decode(data)
            if collect:
                collected.append(output)
                continue
            pending += output
            lines, sep, pending = pending.rpartition('\n')
            if sep:
                emit(lines.replace('\r\n', '\n').removesuffix('\r'))
            if len(pending) >= MAX_FRAME_BYTES:
                emit(pending)
                pending = ''
            continue
        if kind == b'X' and mode == 'shell':
            tail = decoder.decode(b'', final=True)
            exit_code = int(data)
            message = f'Elevated command exited with code {exit_code}'
            if collect:
                collected.append(tail)
                output = ''.join(collected).replace('\r\n', '\n')
                if output:
                    separator = '' if output.endswith('\n') else '\n'
                    message = output + separator + message
            elif pending or tail:
                emit(pending + tail)
            return int(exit_code == 0), message
        raise OSError('Unexpected response from elevated helper')
