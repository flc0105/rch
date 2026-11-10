import json
import os

from core.artifact_contract import ArtifactType, ArtifactSourceKind
from client.http.client_api import ClientApiClient


def _extract_script_context(context) -> dict:
    """
    支持两种传法：
    - context=kwargs
    - context=kwargs.get('__context__', {})
    """
    if not isinstance(context, dict):
        return {}

    nested = context.get('__context__')
    if isinstance(nested, dict):
        return nested

    return context


def _resolve_script_name(metadata=None, script_name: str = '') -> str:
    """
    只解析脚本名，不把整份 SCRIPT_METADATA 作为 artifact meta 上传。
    """
    explicit_name = str(script_name or '').strip()
    if explicit_name:
        return explicit_name

    if isinstance(metadata, dict):
        return str(metadata.get('name') or '').strip()

    return ''


def _build_script_upload_form_data(
    *,
    context=None,
    metadata=None,
    script_name: str = '',
    artifact_type: str = 'files',
    folder: str = '',
) -> dict:
    ctx = _extract_script_context(context)
    resolved_script_name = _resolve_script_name(
        metadata=metadata,
        script_name=script_name,
    )

    form_data = {
        'artifact_type': (artifact_type or 'files').strip() or 'files',
        'source_kind': ArtifactSourceKind.SCRIPT_FILE.value if artifact_type != ArtifactType.SHARED_FILES.value else ArtifactSourceKind.SHARED_UPLOAD.value,
        'folder': str(folder or '').strip(),
        'client_id': str(ctx.get('client_id') or '').strip(),
        'source_command_id': ctx.get('command_id') if ctx.get('command_id') is not None else '',
    }

    # artifact meta 只带 script_name，一个字段，不带整份 SCRIPT_METADATA
    if resolved_script_name:
        form_data['extra'] = json.dumps(
            {
                'script_name': resolved_script_name,
            },
            ensure_ascii=False,
        )

    return form_data


def upload_file(
    file_source,
    *,
    filename: str = '',
    folder: str = '',
    artifact_type: str = 'files',
    context=None,
    metadata=None,
    script_name: str = '',
    timeout=30,
):
    """
    script 专用上传入口。

    用法：
        from client.script_api import upload_file

        resp = upload_file(
            buf,
            filename='a.png',
            folder='Downloads',
            context=kwargs,
            metadata=SCRIPT_METADATA,
        )

    注意：
    - file_source 可以是本地路径，也可以是 BytesIO / file-like 对象
    - script 不需要自己拼 UPLOAD_BASE_URL
    - artifact extra 里只会放 script_name
    """
    if file_source is None:
        raise ValueError('file_source is required')

    form_data = _build_script_upload_form_data(
        context=context,
        metadata=metadata,
        script_name=script_name,
        artifact_type=artifact_type,
        folder=folder,
    )

    upload_name = str(filename or '').strip()
    if not upload_name:
        if isinstance(file_source, str):
            upload_name = os.path.basename(file_source)
        else:
            upload_name = str(getattr(file_source, 'name', '') or '').strip()
    if not upload_name:
        upload_name = 'upload.bin'

    return ClientApiClient().upload_file_source(
        file_source,
        filename=upload_name,
        form_data=form_data,
        timeout=timeout,
    )