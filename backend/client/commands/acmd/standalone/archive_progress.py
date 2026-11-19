"""Per-file progress and skipped-input warnings for ACMD archive commands."""

import time


class ArchiveProgress:
    def __init__(self, owner, action: str, *, verbose: bool = False):
        self.owner = owner
        self.action = action
        self.verbose = verbose
        self.files = 0
        self.bytes = 0
        self.skipped_count = 0
        self.started = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def begin(self, source: str, destination: str):
        if self.verbose:
            self.owner.emit_progress(f'{self.action}: {source} -> {destination}')

    def __call__(self, kind: str, path: str, value=0):
        if kind == 'skipped':
            self.skipped_count += 1
            self.owner.emit_progress(f'Skipped unreadable: {path} ({value})', level='warning')
            return
        self.files += 1
        self.bytes += int(value)
        if self.verbose:
            self.owner.emit_progress(f'{self.action} file: {path}')
