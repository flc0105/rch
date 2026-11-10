"""Publish an artifact creation through the shared Server event bus."""


def publish_artifact_created(event_bus, artifact_info: dict):
    if not isinstance(artifact_info, dict):
        return
    event_bus.publish('artifact_created', {
        'artifact_id': artifact_info.get('artifact_id', ''),
        'artifact_type': artifact_info.get('artifact_type', ''),
        'category': artifact_info.get('category', ''),
        'hostname': artifact_info.get('hostname', ''),
        'machine_id': artifact_info.get('machine_id', ''),
        'client_id': artifact_info.get('client_id', ''),
        'source_command_id': artifact_info.get('source_command_id'),
        'original_name': artifact_info.get('original_name', ''),
        'stored_name': artifact_info.get('stored_name', ''),
        'size': artifact_info.get('size', 0),
        'created_at': artifact_info.get('created_at', ''),
        'download_url': artifact_info.get('download_url', ''),
        'preview_url': artifact_info.get('preview_url', ''),
    })
