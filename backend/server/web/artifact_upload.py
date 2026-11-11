from server.web.request_parsers import (
    get_optional_form_text,
    get_required_upload,
    parse_optional_int_form,
    parse_optional_json_form,
)


def save_uploaded_artifact_from_request(artifact_api):
    """Parse the canonical Artifact upload form."""
    from flask import request
    if 'source_kind' in request.form:
        raise ValueError('source_kind is not a supported Artifact upload field')
    if 'job_name' in request.form or 'job_key' in request.form:
        raise ValueError('Job metadata is stored in the job ledger, not Artifact')
    upload = get_required_upload()
    artifact = artifact_api.save_http_uploaded_file(
        upload,
        artifact_type=get_optional_form_text('artifact_type', 'files'),
        client_id=get_optional_form_text('client_id', ''),
        hostname=get_optional_form_text('hostname', ''),
        machine_id=get_optional_form_text('machine_id', ''),
        job_id=get_optional_form_text('job_id', ''),
        source_command_id=parse_optional_int_form('source_command_id'),
        transfer_buffer_size=parse_optional_int_form('transfer_buffer_size'),
        extra=parse_optional_json_form('extra'),
        category=get_optional_form_text('category') if 'category' in request.form else None,
        folder_id=get_optional_form_text('folder_id', ''),
        folder=get_optional_form_text('folder', ''),
    )

    return artifact
