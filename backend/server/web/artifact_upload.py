from server.web.request_parsers import (
    get_optional_form_text,
    get_required_upload,
    parse_optional_int_form,
    parse_optional_json_form,
)


def save_uploaded_artifact_from_request(artifact_api):
    """Parse the shared HTTP artifact-upload form and persist the artifact."""
    upload = get_required_upload()
    # source_type = get_optional_form_text('source_type', 'client_upload')
    # related_path = get_optional_form_text('related_path', '')
    return artifact_api.save_http_uploaded_file(
        upload,
        artifact_type=get_optional_form_text('artifact_type', 'files'),
        category=get_optional_form_text('category', ''),
        client_id=get_optional_form_text('client_id', ''),
        hostname=get_optional_form_text('hostname', ''),
        machine_id=get_optional_form_text('machine_id', ''),
        job_id=get_optional_form_text('job_id', ''),
        job_name=get_optional_form_text('job_name', ''),
        job_key=get_optional_form_text('job_key', ''),
        # source_type=source_type,
        # related_path=related_path,
        source_command_id=parse_optional_int_form('source_command_id'),
        transfer_buffer_size=parse_optional_int_form('transfer_buffer_size'),
        extra=parse_optional_json_form('extra'),
    )
