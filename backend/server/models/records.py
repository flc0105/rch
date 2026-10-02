"""Shared persisted record shapes.

Output EOF belongs to output chunks; it is not task lifecycle state.
"""

from dataclasses import asdict, dataclass


@dataclass
class LifecycleRecordBase:
    """Common identity and lifecycle timestamps shared by task/history/job records."""

    machine_id: str = ''
    client_id: str = ''
    hostname: str = ''
    addr: str = ''
    created_at: str = ''
    started_at: str = ''
    updated_at: str = ''
    finished_at: str = ''

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OutputRecordBase:
    """Common persisted output chunk shape used by history and background jobs."""

    seq: int = 0
    status: int = 1
    text: str = ''
    eof: int = 0
    created_at: str = ''

    @classmethod
    def from_dict(cls, payload: dict | None):
        source = payload if isinstance(payload, dict) else {}
        return cls(
            seq=int(source.get('seq', 0) or 0),
            status=int(source.get('status', 1) or 0),
            text=str(source.get('text') or ''),
            eof=int(source.get('eof', 0) or 0),
            created_at=str(source.get('created_at') or ''),
        )

    def to_dict(self) -> dict:
        return asdict(self)
