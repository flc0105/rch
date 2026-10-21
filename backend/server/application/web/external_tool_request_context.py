import logging
from dataclasses import dataclass
from typing import Any, Mapping


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExternalToolPayloadContext:
    payload: dict
    params: dict
    instance_id: str = ''


@dataclass(frozen=True)
class ExternalToolClientPayloadContext(ExternalToolPayloadContext):
    tab_id: str = ''
    platform_alias: str = ''
    arch: str = ''


class ExternalToolRequestContextApi:
    """Parse request-like payloads and resolve external-tool target context."""

    def __init__(self, catalog_service, server):
        self.catalog_service = catalog_service
        self.server = server

    def payload(self, payload: Any) -> ExternalToolPayloadContext:
        normalized_payload, params = self._params_from_payload(payload)
        return ExternalToolPayloadContext(
            payload=normalized_payload,
            params=params,
            instance_id=str(normalized_payload.get('instance_id') or '').strip(),
        )

    def client_payload(self, client_id: str, payload: Any, tab_id: str = '') -> ExternalToolClientPayloadContext:
        normalized_payload, params = self._params_from_payload(payload)
        platform_alias, arch = self.resolve_client_target(client_id, normalized_payload)
        return ExternalToolClientPayloadContext(
            payload=normalized_payload,
            params=params,
            instance_id=str(normalized_payload.get('instance_id') or '').strip(),
            tab_id=str(tab_id or '').strip(),
            platform_alias=platform_alias,
            arch=arch,
        )

    def target_from_query(self, query: Mapping[str, Any]):
        platform_alias = str(query.get('platform') or query.get('platform_alias') or '').strip()
        arch = str(query.get('arch') or query.get('architecture') or '').strip()
        return self._normalize_required_target(platform_alias, arch)

    def max_bytes_from_query(self, query: Mapping[str, Any]):
        return query.get('bytes') or query.get('max_bytes') or None

    def resolve_client_target(self, client_id: str, payload: Any):
        requested_platform, requested_arch = self._target_from_payload(payload or {})
        session_platform, session_arch, session_info = self._client_session_target(client_id)

        requested_platform_norm = self.catalog_service._normalize_platform(requested_platform)
        requested_arch_norm = self.catalog_service._normalize_arch(requested_arch)
        session_platform_norm = self.catalog_service._normalize_platform(session_platform)
        session_arch_norm = self.catalog_service._normalize_arch(session_arch)

        logger.info(
            '[external-tools] client target check: client_id=%s machine_id=%s hostname=%s requested=%s/%s session=%s/%s',
            client_id,
            getattr(session_info, 'machine_id', '') if session_info else '',
            getattr(session_info, 'hostname', '') if session_info else '',
            requested_platform_norm or 'unknown',
            requested_arch_norm or 'unknown',
            session_platform_norm or 'unknown',
            session_arch_norm or 'unknown',
        )

        if requested_platform_norm != session_platform_norm or requested_arch_norm != session_arch_norm:
            raise ValueError(
                'target platform/arch mismatch: '
                f'client_id={client_id} requested={requested_platform_norm or "unknown"}/{requested_arch_norm or "unknown"} '
                f'session={session_platform_norm or "unknown"}/{session_arch_norm or "unknown"}'
            )

        return session_platform_norm, session_arch_norm

    def _params_from_payload(self, payload: Any):
        normalized_payload = payload if isinstance(payload, dict) else {}
        params = normalized_payload.get('params') or {}
        if not isinstance(params, dict):
            raise ValueError('params must be an object')
        return normalized_payload, params

    def _target_from_payload(self, payload: Mapping[str, Any]):
        platform_alias = str(payload.get('platform') or payload.get('platform_alias') or '').strip()
        arch = str(payload.get('arch') or payload.get('architecture') or '').strip()
        return self._normalize_required_target(platform_alias, arch)

    def _normalize_required_target(self, platform_alias: str, arch: str):
        if not platform_alias or not arch:
            raise ValueError(f'target platform and arch are required, got {platform_alias or "unknown"}/{arch or "unknown"}')
        return (
            self.catalog_service._normalize_platform(platform_alias),
            self.catalog_service._normalize_arch(arch),
        )

    def _client_session_target(self, client_id: str):
        session = self.server.get_target_connection_by_client_id(client_id)
        session_info = getattr(session, 'session_info', None)
        if session_info is None:
            raise ValueError(f'target client session info not found: {client_id}')

        platform_alias = str(
            getattr(session_info, 'os_alias', '') or
            getattr(session_info, 'os_type', '') or
            ''
        ).strip()
        arch = str(getattr(session_info, 'arch', '') or '').strip()

        if not platform_alias or not arch:
            raise ValueError(f'target client session is missing platform/arch: client_id={client_id} target={platform_alias or "unknown"}/{arch or "unknown"}')

        return platform_alias, arch, session_info
