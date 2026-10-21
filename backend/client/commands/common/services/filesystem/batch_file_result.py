"""One result contract for remote batch file mutations."""
from dataclasses import dataclass


@dataclass(frozen=True)
class BatchFileResult:
    action: str
    total: int
    succeeded: int
    errors: tuple[str, ...]
    destination: str = ''

    @property
    def failed(self) -> int:
        return self.total - self.succeeded

    @property
    def status(self) -> int:
        return int(self.succeeded > 0)

    def to_dict(self) -> dict:
        verb = {'delete': 'Deleted', 'copy': 'Copied', 'move': 'Moved'}[self.action]
        message = f'{verb} {self.succeeded} of {self.total} items'
        if self.destination:
            message += f' to: {self.destination}'
        if self.errors:
            message += '\nErrors:\n  ' + '\n  '.join(self.errors)
        return {
            'status': self.status, 'total': self.total,
            'succeeded': self.succeeded, 'failed': self.failed,
            'message': message, 'errors': list(self.errors),
        }
