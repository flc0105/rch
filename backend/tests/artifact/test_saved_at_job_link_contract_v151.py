"""Artifact timestamps and Job references use one canonical SQLite representation."""
import json
import re
import sqlite3

import pytest

from server.application.artifact.artifact_sqlite_catalog import ArtifactSqliteCatalog
from server.application.artifact.command_output_artifact_service import CommandOutputArtifactService
from server.application.jobs.background_job_store import BackgroundJobStore
from server.persistence.rch_database import RchDatabase


def test_artifact_saved_at_is_the_only_registration_timestamp(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    catalog = ArtifactSqliteCatalog(db)
    file_path = tmp_path / 'report.txt'
    file_path.write_text('report', encoding='utf-8')
    row = {
        'artifact_id': 'a-1', 'scope': 'saved', 'category': 'command_output',
        'original_name': 'report.txt', 'machine_id': 'machine-1',
        'saved_path': str(file_path), 'saved_at': '2026-11-11 12:00:00',
        'extra': {'saved_from': 'terminal_output'},
    }
    saved = catalog.save(row)
    assert saved['folder_id'] == 'saved:command_output'
    assert saved['saved_at'] == '2026-11-11 12:00:00'
    assert 'created_at' not in saved
    assert 'saved_at' not in saved['extra']
    with sqlite3.connect(db.db_path) as conn:
        names = [entry[1] for entry in conn.execute('PRAGMA table_info(artifact_entries)')]
        payload = json.loads(conn.execute('SELECT payload_json FROM artifact_entries').fetchone()[0])
    assert 'saved_at' in names and 'created_at' not in names
    assert 'created_at' not in payload and 'saved_at' in payload
    assert catalog.get('a-1')['saved_at'] == saved['saved_at']


def test_job_artifact_relation_is_in_link_table_not_artifact_payload(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    catalog = ArtifactSqliteCatalog(db)
    store = BackgroundJobStore(db)
    with db.transaction() as conn:
        conn.execute("INSERT INTO background_jobs(job_id, machine_id, client_id, job_key, job_name) "
                     "VALUES ('job-1', 'machine-1', 'client-1', 'clipboard_monitor', 'ClipboardMonitor')")
    path = tmp_path / 'monitor.json'
    path.write_text('{}', encoding='utf-8')
    artifact = catalog.save({
        'artifact_id': 'artifact-1', 'scope': 'saved', 'category': 'command_output',
        'machine_id': 'machine-1', 'saved_path': str(path),
        'saved_at': '2026-11-11 13:33:50', 'original_name': 'monitor.json',
        'extra': {'saved_from': 'background_job_detail'},
    })
    store.link_artifact('job-1', artifact)
    store.link_artifact('job-1', artifact)
    assert store.artifact_job_links(['artifact-1']) == {'artifact-1': [{
        'job_id': 'job-1', 'job_key': 'clipboard_monitor', 'job_name': 'ClipboardMonitor',
    }]}
    assert store.artifact_job_links(['none'] * 700) == {}
    assert store.artifact_job_links([f'missing-{i}' for i in range(1100)]) == {}
    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM background_job_files').fetchone()[0] == 1
    assert not {'job_id', 'job_key', 'job_name'} & set(catalog.get('artifact-1'))
    with pytest.raises(ValueError, match='not found'):
        store.link_artifact('missing', artifact)


def test_output_kind_selects_script_path_job_key_and_json_extension(tmp_path):
    class OutputSink:
        def allocate_artifact_path(self, **kwargs):
            return {'machine_id': 'machine-1', 'file_path': str(tmp_path / kwargs['original_name']),
                    'original_name': kwargs['original_name'], 'stored_name': kwargs['original_name']}

        def register_existing_artifact(self, **kwargs):
            return kwargs

    service = CommandOutputArtifactService(OutputSink())
    assert re.fullmatch(r'script_\d{8}_\d{6}_list_disks\.json', service.build_output_name(
        output_kind='script', source_command='script exec common/recon/list_disks.py',
        script_path='common/recon/list_disks.py', output_format='json'))
    assert re.fullmatch(r'job_output_\d{8}_\d{6}_clipboard_monitor\.json', service.build_output_name(
        output_kind='job', source_command='', job_key='clipboard_monitor', output_format='json'))
    saved = service.save_text_output(
        content='{"done":true}', output_kind='script', hostname='mac', machine_id='machine-1',
        source_command='script exec common/recon/list_disks.py', output_format='json',
        extra={'saved_from': 'terminal_json_viewer', 'script_path': 'common/recon/list_disks.py'},
    )
    assert saved['original_name'].endswith('_list_disks.json')
    assert saved['extra'] == {'saved_from': 'terminal_json_viewer',
                             'source_command': 'script exec common/recon/list_disks.py',
                             'script_path': 'common/recon/list_disks.py'}
    with pytest.raises(ValueError, match='Unsupported output metadata'):
        service.build_extra(source_command='', extra={'saved_from': 'terminal_output', 'source': 'old'})
    with pytest.raises(ValueError, match='script_path'):
        service.build_output_name(output_kind='script', source_command='script')
    with pytest.raises(ValueError, match='job_key'):
        service.build_output_name(output_kind='job', source_command='')
