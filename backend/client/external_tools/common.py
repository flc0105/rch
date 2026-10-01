import os
import platform

from core.external_tools.files import read_json_file_or_empty, write_json_file
from core.external_tools.paths import (
    build_command_map,
    chmod_executable,
    expand_path,
    is_url_like,
    path_has_content,
    render_path_list,
    sanitize_instance_id,
    should_expand_argv_item,
)
from core.platform.normalization import normalize_arch, normalize_platform
from core.external_tools.target import runtime_parts_from_payload as parse_runtime_parts_from_payload
from core.external_tools.target import validate_payload_target
from core.platform.platform_identity import detect_platform_alias


class ExternalToolCommon:
    """Common helpers shared by client-side external tool modules."""

    DOWNLOAD_TIMEOUT = (15, 600)
    DOWNLOAD_CHUNK_SIZE = 64 * 1024
    DEFAULT_STOP_TIMEOUT_SEC = 5
    DEFAULT_LOG_TAIL_BYTES = 65536

    @property
    def client_api(self):
        return self.command_host.client_api

    def _ensure_not_interrupted(self):
        return self.command_host._ensure_not_interrupted()

    def normalize_platform(self, value) -> str:
        return normalize_platform(value)

    def normalize_arch(self, value) -> str:
        return normalize_arch(value)

    def local_target(self) -> tuple[str, str]:
        local_platform = self.normalize_platform(detect_platform_alias())
        local_arch = self.normalize_arch(platform.machine())
        if not local_platform or not local_arch:
            raise ValueError(f'unable to detect local platform/arch, got {local_platform or "unknown"}/{local_arch or "unknown"}')
        return local_platform, local_arch

    def validate_package_payload(self, payload: dict, action: str = '') -> tuple[str, str]:
        local_platform, local_arch = self.local_target()
        return validate_payload_target(payload, local_platform, local_arch, action=action)

    def expand_path(self, path: str) -> str:
        return expand_path(path)

    def sanitize_instance_id(self, value) -> str:
        return sanitize_instance_id(value)

    def render_path_list(self, values):
        return render_path_list(values)

    def is_url_like(self, value: str) -> bool:
        return is_url_like(value)

    def should_expand_argv_item(self, value: str, index: int) -> bool:
        return should_expand_argv_item(value, index)

    def chmod(self, path: str):
        chmod_executable(path)

    def build_command_map(self, exec_paths: dict) -> dict:
        return build_command_map(exec_paths, self.expand_path)

    def path_has_content(self, path: str) -> bool:
        return path_has_content(path)

    def read_json(self, path: str) -> dict:
        return read_json_file_or_empty(path)

    def write_json(self, path: str, data: dict):
        write_json_file(path, data)

    def runtime_parts_from_payload(self, payload: dict) -> tuple[str, str, str]:
        return parse_runtime_parts_from_payload(payload)
