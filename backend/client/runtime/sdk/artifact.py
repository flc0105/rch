import builtins
import json
import os
from typing import Any

from client.http.client_api import ClientApiClient, ClientApiError
from client.runtime.sdk.context import get_client_id, get_command_id, get_command_owner


class ScriptSdkArtifactError(RuntimeError):
    """Script SDK artifact 统一异常。"""
    pass


FORMAL_ARTIFACT_TYPES = {'files', 'previews', 'shared_files', 'command_output'}


def _safe_text(value) -> str:
    return '' if value is None else str(value).strip()


def _normalize_artifact_type(value: str, default: str = 'files') -> str:
    artifact_type = _safe_text(value) or default
    if artifact_type not in FORMAL_ARTIFACT_TYPES:
        raise ValueError(f'Unsupported artifact type: {artifact_type}')
    return artifact_type


def _unwrap_api_payload(payload: dict) -> Any:
    if not isinstance(payload, dict):
        return payload
    code = payload.get('code', 0)
    if code != 0:
        raise ClientApiError(str(payload.get('message') or 'Server API request failed'))
    return payload.get('data') if 'data' in payload else payload


def _build_form_data(*, artifact_type: str, category: str, extra: dict | None = None) -> dict:
    owner = get_command_owner()
    if owner is not None and hasattr(owner, 'http_file_transfer_service'):
        return owner.http_file_transfer_service.build_http_upload_form_data(
            artifact_type=artifact_type,
            category=category,
            extra=extra,
        )

    payload = {
        'artifact_type': artifact_type,
        'category': category,
        'client_id': get_client_id(),
        'source_command_id': get_command_id() if get_command_id() is not None else '',
    }
    if isinstance(extra, dict) and extra:
        payload['extra'] = json.dumps(extra, ensure_ascii=False)
    return payload


def _resolve_local_file(path: str) -> str:
    file_path = _safe_text(path)
    if not file_path:
        raise ValueError('path is required')

    owner = get_command_owner()
    if owner is not None and hasattr(owner, 'path_resolver'):
        return owner.path_resolver.require_existing_file_from_arg(file_path)

    resolved_path = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.isfile(resolved_path):
        raise FileNotFoundError(f'file not found: {resolved_path}')
    return resolved_path


def _resolve_target_path(target_path: str, default_name: str) -> str:
    normalized_target = _safe_text(target_path)
    filename = os.path.basename(default_name) or 'artifact.bin'
    owner = get_command_owner()

    if not normalized_target:
        return os.path.abspath(filename)

    if owner is not None and hasattr(owner, 'path_resolver'):
        resolved_target = owner.path_resolver.resolve_target_path(normalized_target)
    else:
        resolved_target = os.path.abspath(os.path.expanduser(normalized_target))

    if normalized_target.endswith(('/', '\\')) or os.path.isdir(resolved_target):
        os.makedirs(resolved_target, exist_ok=True)
        return os.path.join(resolved_target, filename)

    target_dir = os.path.dirname(resolved_target)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)
    return resolved_target


def _parse_upload_response(response, file_path: str) -> dict:
    response.raise_for_status()
    payload = ClientApiClient().try_parse_json(response)
    data = _unwrap_api_payload(payload if isinstance(payload, dict) else {})
    if not isinstance(data, dict):
        raise ScriptSdkArtifactError(f'Invalid artifact upload response: {file_path}')
    return data


def save(path: str, *, type: str = 'files', category: str = 'script', extra: dict | None = None,
         timeout=None) -> dict:
    """
    上传 client 本地文件到 server artifact。

    用法：
        item = artifact.save('/tmp/a.log')
        item = artifact.save('/tmp/a.log', type='shared_files')
    """
    artifact_type = _normalize_artifact_type(type, default='files')
    normalized_category = _safe_text(category) or 'script'
    file_path = _resolve_local_file(path)
    owner = get_command_owner()

    if owner is not None and hasattr(owner, 'http_file_transfer_service'):
        response = owner.http_file_transfer_service.upload_file_to_server_via_http(
            file_path,
            artifact_type=artifact_type,
            category=normalized_category,
            extra=extra,
        )
        return _parse_upload_response(response, file_path)

    response = ClientApiClient().upload_file_source(
        file_path,
        filename=os.path.basename(file_path),
        form_data=_build_form_data(
            artifact_type=artifact_type,
            category=normalized_category,
            extra=extra,
        ),
        timeout=timeout or 120,
    )
    return _parse_upload_response(response, file_path)


def list(type: str = '', machine_id: str = '') -> list[dict]:
    """列出 server artifact。"""
    params = {}
    if _safe_text(type):
        params['type'] = _normalize_artifact_type(type, default='files')
    if _safe_text(machine_id):
        params['machine_id'] = _safe_text(machine_id)

    data = ClientApiClient().get_data('/api/artifacts', params=params, timeout=15)
    if isinstance(data, dict):
        items = data.get('items') or []
        return items if isinstance(items, builtins.list) else []
    return []

def find_by_file_name(file_name: str, *, type: str = '', machine_id: str = '', exact: bool = True) -> builtins.list[dict]:
    """按文件名查找 server artifact，返回基础信息列表。"""
    target = _safe_text(file_name)
    if not target:
        raise ValueError('file_name is required')

    candidates = list(type=type, machine_id=machine_id)
    results = []

    for item in candidates:
        if not isinstance(item, dict):
            continue

        original_name = _safe_text(item.get('original_name'))
        stored_name = _safe_text(item.get('stored_name'))
        names = [name for name in [original_name, stored_name] if name]

        if exact:
            matched = target in names
        else:
            lowered_target = target.lower()
            matched = any(lowered_target in name.lower() for name in names)

        if not matched:
            continue

        results.append({
            'filename': original_name or stored_name,
            'artifact_id': item.get('artifact_id', ''),
            'created_at': item.get('created_at', ''),
            'size': int(item.get('size', 0) or 0),
            'machine_id': item.get('machine_id', ''),
            'hostname': item.get('hostname', ''),
            'artifact_type': item.get('artifact_type', ''),
        })

    return results


def _resolve_artifact(ref: str, artifact_type: str) -> dict:
    target = _safe_text(ref)
    if not target:
        raise ValueError('artifact ref is required')

    candidates = list(type=artifact_type)
    matched = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        names = {
            _safe_text(item.get('artifact_id')),
            _safe_text(item.get('original_name')),
            _safe_text(item.get('stored_name')),
        }
        if target in names:
            matched.append(item)

    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        raise ScriptSdkArtifactError(f'Multiple artifacts matched: {target}')
    raise FileNotFoundError(f'artifact not found: {target}')


def download(ref: str, *, type: str = 'shared_files', target_path: str = '', timeout=None) -> str:
    """
    从 server artifact 下载到 client 本地。

    用法：
        local_path = artifact.download('artifact_id', type='shared_files')
        local_path = artifact.download('tool.zip', type='shared_files', target_path='./downloads/')
    """
    artifact_type = _normalize_artifact_type(type, default='shared_files')
    item = _resolve_artifact(ref, artifact_type)
    filename = item.get('original_name') or item.get('stored_name') or item.get('artifact_id') or 'artifact.bin'
    local_path = _resolve_target_path(target_path, filename)
    download_url = item.get('download_url') or f'/api/artifacts/{item.get("artifact_id")}/download'
    owner = get_command_owner()
    checkpoint = getattr(owner, '_checkpoint', None) if owner is not None else None

    ClientApiClient().download_file(
        download_url,
        local_path,
        timeout=timeout,
        checkpoint=checkpoint if callable(checkpoint) else None,
    )
    return local_path


def get(ref: str, *, type: str = 'shared_files') -> dict:
    return _resolve_artifact(ref, _normalize_artifact_type(type, default='shared_files'))


# 语义化别名，方便脚本里按动作阅读。
list_artifacts = list
find_artifacts_by_file_name = find_by_file_name
save_file = save
download_file = download
