"""Script command identity and HTTP Bundle/Job uploads share the current API contract."""
from unittest.mock import Mock

from core.protocol.structured_arg_codec import encode_structured_arg
from server.application.web.artifact_api import WebArtifactApi
from server.application.web.command_execution_api import WebCommandExecutionApi


def test_browser_bundle_upload_never_forwards_job_id_to_artifact_storage():
    class Storage:
        # Deliberately use the ArtifactService's real keyword contract: an
        # unexpected job_id used to raise the production TypeError here.
        def save_http_uploaded_file(self, upload, *, artifact_type, category,
                                    client_id, hostname, machine_id,
                                    source_command_id, addr, transfer_buffer_size,
                                    extra, folder_id):
            assert category == 'downloads'
            assert extra == {'saved_from': 'remote_file_browser'}
            return {'artifact_id': 'bundle-a', 'category': category}

    api = WebArtifactApi(None, None, Storage())
    api.publish_artifact_created = lambda _artifact: None
    item = api.save_http_uploaded_file(
        Mock(), artifact_type='saved', category='downloads',
        extra={'saved_from': 'remote_file_browser'},
    )
    assert item['artifact_id'] == 'bundle-a'


def test_job_upload_keeps_ledger_link_without_forwarding_job_id_to_storage():
    service = Mock()
    service.save_http_uploaded_file.return_value = {'artifact_id': 'job-file-a'}
    store = Mock()
    store.get_job_for_scope.return_value = {'job_id': 'job-a'}
    api = WebArtifactApi(None, None, service, background_job_store=store)
    api.publish_artifact_created = lambda _artifact: None
    artifact = api.save_http_uploaded_file(Mock(), job_id='job-a', category='job_files')
    assert 'job_id' not in service.save_http_uploaded_file.call_args.kwargs
    store.link_artifact.assert_called_once_with('job-a', artifact)


def test_generic_web_command_submission_never_infers_builtin_metadata():
    task_service = Mock()
    task_service.submit_web_command.side_effect = lambda _client, command, **kwargs: {
        'command': command, 'metadata': kwargs['metadata'],
    }
    api = WebCommandExecutionApi(task_service)
    payload = {'script_name': 'tools/check.py', 'params': {}}
    for command in (
        'script exec "common/recon/list_disks.py" --json',
        f'script run {encode_structured_arg(payload)}',
        'script list',
        'shell echo script exec tools/check.py',
        'script run __json__:invalid',
        'script exec "unterminated',
    ):
        result = api.submit_web_command('client-a', command)
        assert result['command'] == command
        assert result['metadata'] == {}


def test_generic_web_command_passes_metadata_without_mutating_the_caller():
    service = Mock()
    api = WebCommandExecutionApi(service)
    original = {'operation_id': 'op-a', 'script_run': True,
                'script_run_name': 'tools/check.py', 'script_run_presentation': 'dialog'}
    api.submit_web_command(' client-a ', ' script exec tools/check.py ',
                           tab_id=' tab-a ', source=' web_script ', metadata=original)
    args, kwargs = service.submit_web_command.call_args
    assert args == ('client-a', 'script exec tools/check.py')
    assert kwargs == {
        'tab_id': 'tab-a', 'source': 'web_script', 'metadata': original,
    }
    assert kwargs['metadata'] is not original
    assert original == {'operation_id': 'op-a', 'script_run': True,
                        'script_run_name': 'tools/check.py', 'script_run_presentation': 'dialog'}


def test_script_api_provenance_is_preserved_without_extra_inferred_fields():
    service = Mock()
    api = WebCommandExecutionApi(service)
    original = {'script_run': True, 'script_run_name': 'tools/check.py',
                'script_run_presentation': 'dialog', 'operation_id': 'op-a'}
    api.submit_web_command('client-a', 'script exec tools/check.py', metadata=original)
    assert service.submit_web_command.call_args.kwargs['metadata'] == original


def test_script_dialog_supplies_identity_through_its_own_api():
    from server.application.web.script_api import WebScriptApi

    task_service = Mock()
    task_service.submit_web_command.side_effect = lambda _client, command, **kwargs: {
        'command': command, 'metadata': kwargs['metadata'],
    }
    script_catalog = Mock()
    script_catalog.list_scripts.return_value = []
    api = WebScriptApi(WebCommandExecutionApi(task_service), script_catalog)
    result = api.run_script('client-a', 'common/recon/list_disks.py', params={},
                            presentation='dialog', run_id='run-a', operation_id='op-a')
    assert result['command'].startswith('script run __json__:')
    assert result['metadata']['script_run'] is True
    assert result['metadata']['script_run_name'] == 'common/recon/list_disks.py'
    assert result['metadata']['script_run_presentation'] == 'dialog'
    assert result['metadata']['script_run_id'] == 'run-a'
    assert result['metadata']['operation_id'] == 'op-a'


def test_terminal_json_viewer_output_uses_script_name_and_text_extension(tmp_path):
    from datetime import datetime
    from server.application.artifact.command_output_artifact_service import CommandOutputArtifactService

    class OutputSink:
        def allocate_artifact_path(self, **kwargs):
            return {'machine_id': 'machine-a', 'original_name': kwargs['original_name'],
                    'file_path': str(tmp_path / kwargs['original_name']),
                    'stored_name': kwargs['original_name']}

        def register_existing_artifact(self, **kwargs):
            return kwargs

    service = CommandOutputArtifactService(OutputSink())
    service._now = lambda: datetime(2026, 11, 11, 15, 48, 51)
    saved = service.save_text_output(
        content='[{"name":"disk"}]', output_kind='script', output_format='text',
        machine_id='machine-a', hostname='mac',
        source_command='script exec common/recon/list_disks.py',
        extra={'saved_from': 'terminal_json_viewer',
               'script_path': 'common/recon/list_disks.py'},
    )
    assert saved['original_name'] == 'script_20261111_154851_list_disks.txt'
    assert (tmp_path / saved['original_name']).read_text() == '[{"name":"disk"}]'
