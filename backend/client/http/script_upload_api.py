import json
import os

from core.artifact_contract import ArtifactType
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
    artifact_type: str = 'saved',
    category: str = '',
    folder: str = '',
) -> dict:
    if folder and artifact_type != ArtifactType.SHARED.value:
        raise ValueError('Saved Files use category, not folder')
    if category and artifact_type == ArtifactType.SHARED.value:
        raise ValueError('Only Saved Files can have category')
    ctx = _extract_script_context(context)
    resolved_script_name = _resolve_script_name(
        metadata=metadata,
        script_name=script_name,
    )

    form_data = {
        'artifact_type': (artifact_type or 'saved').strip() or 'saved',
        **({'category': str(category).strip()} if artifact_type == ArtifactType.SAVED.value and str(category or '').strip() else {}),
        **({'folder': str(folder).strip()} if artifact_type == ArtifactType.SHARED.value and folder else {}),
        'client_id': str(ctx.get('client_id') or '').strip(),
        'source_command_id': ctx.get('command_id') if ctx.get('command_id') is not None else '',
    }

    extra = {'saved_from': 'script_sdk'}
    script_path = str(ctx.get('script_path') or '').strip()
    if script_path:
        extra['script_path'] = script_path
    form_data['extra'] = json.dumps(extra, ensure_ascii=False)

    return form_data


def upload_file(
    file_source,
    *,
    filename: str = '',
    category: str = '',
    folder: str = '',
    artifact_type: str = 'saved',
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
            category='downloads',
            context=kwargs,
            metadata=SCRIPT_METADATA,
        )

    注意：
    - file_source 可以是本地路径，也可以是 BytesIO / file-like 对象
    - Script 通过 ClientApiClient 使用统一 Server Web 地址
    - artifact extra 里只会放 script_name
    """
    if file_source is None:
        raise ValueError('file_source is required')

    form_data = _build_script_upload_form_data(
        context=context,
        metadata=metadata,
        script_name=script_name,
        artifact_type=artifact_type,
        category=category,
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