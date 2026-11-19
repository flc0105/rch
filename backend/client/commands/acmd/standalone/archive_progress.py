"""ACMD-only progress formatting; archive services receive plain callbacks."""

import time


class ArchiveProgress:
    def __init__(self, owner, action: str, *, verbose: bool = False):
        self.owner = owner
        self.action = action
        self.verbose = verbose
        self.files = 0
        self.bytes = 0
        self.skipped = []
        self.started = time.monotonic()
        self.last_update = self.started

    def begin(self, source: str, destination: str):
        self.owner.emit_progress(f'{self.action}: {source} -> {destination}')

    def __call__(self, kind: str, path: str, value=0):
        if kind == 'skipped':
            self.skipped.append({'path': path, 'reason': str(value)})
            self.owner.emit_progress(f'Skipped unreadable: {path} ({value})', level='warning')
            return
        self.files += 1
        self.bytes += int(value)
        if self.verbose:
            self.owner.emit_progress(f'{self.action} file: {path}')
        now = time.monotonic()
        if not self.verbose and now - self.last_update >= 1.0:
            self.owner.emit_progress(f'{self.action}: {self.files} files, {self.bytes} bytes processed')
            self.last_update = now

    def finish(self):
        duration = time.monotonic() - self.started
        skipped = f', skipped {len(self.skipped)} unreadable' if self.skipped else ''
        outcome = 'partial' if self.skipped else 'complete'
        self.owner.emit_progress(
            f'{self.action} {outcome}: {self.files} files, {self.bytes} bytes, '
            f'{duration:.1f}s{skipped}',
            level='warning' if self.skipped else 'success',
        )
