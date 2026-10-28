from dataclasses import dataclass, field


@dataclass
class SessionInfo:
    client_id: str = ''
    addr: str = ''
    hostname: str = 'Unknown'
    machine_id: str = ''
    # machine_id_version: str = ''
    machine_fingerprint_basis: str = ''
    os_type: str = 'Unknown'
    os_alias: str = 'unknown'
    os_full: str = 'Unknown'
    os_name: str = 'Unknown'
    os_ver: str = 'Unknown'
    arch: str = 'Unknown'
    manufacturer: str = 'Unknown'
    model: str = 'Unknown'
    integrity: str = '?'
    cwd: str = ''
    build_version: str = ''
    client_revision: str = ''
    client_revision_files: dict = field(default_factory=dict)
    command_manifest: list[dict] = field(default_factory=list)
    system_paths: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict | None):
        if not isinstance(payload, dict):
            return cls()

        known_keys = {
            'id',
            'addr',
            'hostname',
            'machine_id',
            'machine_id_version',
            'machine_fingerprint_basis',
            'os_type',
            'os_alias',
            'os_ver',
            'os_name',
            'os_full',
            'arch',
            'manufacturer',
            'model',
            'integrity',
            'cwd',
            'build_version',
            'client_revision',
            'client_revision_files',
            'command_manifest',
            'system_paths',
        }

        extras = {
            key: value
            for key, value in payload.items()
            if key not in known_keys
        }

        client_revision_files = payload.get('client_revision_files')
        if not isinstance(client_revision_files, dict):
            client_revision_files = {}

        return cls(
            client_id=str(payload.get('id') or ''),
            addr=str(payload.get('addr') or ''),
            hostname=str(payload.get('hostname') or 'Unknown'),
            machine_id=str(payload.get('machine_id') or ''),
            # machine_id_version=str(payload.get('machine_id_version') or ''),
            machine_fingerprint_basis=str(payload.get('machine_fingerprint_basis') or ''),
            os_type=str(payload.get('os_type') or 'Unknown'),
            os_alias=str(payload.get('os_alias') or 'unknown'),
            os_ver=str(payload.get('os_ver') or 'Unknown'),
            os_name=str(payload.get('os_name') or 'Unknown'),
            os_full=str(payload.get('os_full') or 'Unknown'),
            arch=str(payload.get('arch') or 'Unknown'),
            manufacturer=str(payload.get('manufacturer') or 'Unknown'),
            model=str(payload.get('model') or 'Unknown'),
            integrity=str(payload.get('integrity') or '?'),
            cwd=str(payload.get('cwd') or ''),
            build_version=(payload.get('build_version') or 'Unknown'),
            client_revision=str(payload.get('client_revision') or ''),
            client_revision_files=dict(client_revision_files),
            command_manifest=list(payload.get('command_manifest') or []),
            system_paths=dict(payload.get('system_paths') or {}),
            extras=extras,
        )

    def to_dict(self) -> dict:
        data = {
            'id': self.client_id,
            'addr': self.addr,
            'hostname': self.hostname,
            'machine_id': self.machine_id,
            # 'machine_id_version': self.machine_id_version,
            'machine_fingerprint_basis': self.machine_fingerprint_basis,
            'os_type': self.os_type,
            'os_full': self.os_full,
            'os_alias': self.os_alias,
            'os_name': self.os_name,
            'os_ver': self.os_ver,
            'arch': self.arch,
            'manufacturer': self.manufacturer,
            'model': self.model,
            'integrity': self.integrity,
            'cwd': self.cwd,
            'build_version': self.build_version,
            'client_revision': self.client_revision,
            'client_revision_files': dict(self.client_revision_files),
            'command_manifest': list(self.command_manifest),
            'system_paths': dict(self.system_paths),
        }
        data.update(self.extras or {})
        return data

    # SessionInfo 兼容读取入口
    def get(self, key: str, default=None):
        return self.to_dict().get(key, default)


    def get_extra(self, key: str, default=None):
        return (self.extras or {}).get(key, default)


    def set_extra(self, key: str, value):
        if self.extras is None:
            self.extras = {}
        self.extras[key] = value
