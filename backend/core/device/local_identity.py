import platform
import threading
from dataclasses import dataclass

from core.device.machine_identity import (
    build_machine_identity_payload,
    detect_machine_identity_components,
)
from core.platform.normalization import normalize_arch
from core.platform.platform_identity import detect_platform_info


@dataclass(frozen=True)
class LocalIdentity:
    """Canonical, process-local machine and platform identity."""

    os_alias: str
    os_type: str
    system_name: str
    os_full: str
    hostname: str
    os_name: str
    os_version: str
    arch: str
    manufacturer: str
    model: str
    native_id: str
    machine_id: str
    machine_id_short: str
    machine_id_version: str
    fingerprint_basis: str
    raw_components: dict
    normalized_components: dict

    def machine_identity_payload(self) -> dict:
        return {
            'machine_id_version': self.machine_id_version,
            'machine_id_hash': self.machine_id,
            'machine_id_short': self.machine_id_short,
            'fingerprint_basis': self.fingerprint_basis,
            'raw_components': dict(self.raw_components),
            'normalized_components': dict(self.normalized_components),
        }


_identity_lock = threading.RLock()
_cached_identity: LocalIdentity | None = None


def _build_local_identity() -> LocalIdentity:
    platform_info = detect_platform_info()
    raw = detect_machine_identity_components(platform_info=platform_info)
    machine_payload = build_machine_identity_payload(raw_components=raw)

    raw_arch = str(raw.get('arch') or '').strip()
    normalized_arch = normalize_arch(raw_arch) or raw_arch.lower()

    return LocalIdentity(
        os_alias=str(platform_info.alias or 'unknown'),
        os_type=str(platform_info.display_name or platform_info.system_name or 'Unknown'),
        system_name=str(platform_info.system_name or 'Unknown'),
        os_full=str(platform.platform() or ''),
        hostname=str(raw.get('hostname') or ''),
        os_name=str(raw.get('os_name') or ''),
        os_version=str(raw.get('os_version') or ''),
        arch=normalized_arch,
        manufacturer=str(raw.get('manufacturer') or ''),
        model=str(raw.get('model') or ''),
        native_id=str(raw.get('native_id') or ''),
        machine_id=str(machine_payload.get('machine_id_hash') or ''),
        machine_id_short=str(machine_payload.get('machine_id_short') or ''),
        machine_id_version=str(machine_payload.get('machine_id_version') or ''),
        fingerprint_basis=str(machine_payload.get('fingerprint_basis') or ''),
        raw_components=dict(machine_payload.get('raw_components') or raw),
        normalized_components=dict(machine_payload.get('normalized_components') or {}),
    )


def get_local_identity(*, refresh: bool = False) -> LocalIdentity:
    """
    Return the canonical local machine/platform identity.

    Hardware/platform probing can invoke sysctl, ioreg, registry or DMI reads, so the
    result is cached for the process lifetime. Call with refresh=True only when an
    explicit re-detection is required.
    """
    global _cached_identity
    with _identity_lock:
        if refresh or _cached_identity is None:
            _cached_identity = _build_local_identity()
        return _cached_identity


def clear_local_identity_cache():
    """Clear the process-local identity cache, mainly for tests/explicit refreshes."""
    global _cached_identity
    with _identity_lock:
        _cached_identity = None
