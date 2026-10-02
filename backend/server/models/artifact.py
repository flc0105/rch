from dataclasses import dataclass


@dataclass
class ArtifactReference:
    """Stable artifact reference persisted by consumers such as command history."""

    artifact_id: str = ''
    artifact_type: str = ''
    category: str = ''
    hostname: str = ''
    machine_id: str = ''
    client_id: str = ''
    original_name: str = ''
    stored_name: str = ''
    saved_path: str = ''
    size: int = 0
    created_at: str = ''
    download_url: str = ''
    raw_url: str = ''
    preview_url: str = ''

    @classmethod
    def from_dict(cls, payload: dict | None):
        if not isinstance(payload, dict):
            return cls()
        return cls(
            artifact_id=str(payload.get('artifact_id') or ''),
            artifact_type=str(payload.get('artifact_type') or ''),
            category=str(payload.get('category') or ''),
            hostname=str(payload.get('hostname') or ''),
            machine_id=str(payload.get('machine_id') or ''),
            client_id=str(payload.get('client_id') or ''),
            original_name=str(payload.get('original_name') or ''),
            stored_name=str(payload.get('stored_name') or ''),
            saved_path=str(payload.get('saved_path') or ''),
            size=int(payload.get('size', 0) or 0),
            created_at=str(payload.get('created_at') or ''),
            download_url=str(payload.get('download_url') or ''),
            raw_url=str(payload.get('raw_url') or ''),
            preview_url=str(payload.get('preview_url') or ''),
        )

    def to_dict(self) -> dict:
        return {
            'artifact_id': self.artifact_id,
            'artifact_type': self.artifact_type,
            'category': self.category,
            'hostname': self.hostname,
            'machine_id': self.machine_id,
            'client_id': self.client_id,
            'original_name': self.original_name,
            'stored_name': self.stored_name,
            'saved_path': self.saved_path,
            'size': self.size,
            'created_at': self.created_at,
            'download_url': self.download_url,
            'raw_url': self.raw_url,
            'preview_url': self.preview_url,
        }
