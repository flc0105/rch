import os
import tempfile
import unittest
from types import SimpleNamespace

from server.application.command.command_execution_event import CommandExecutionEvent
from server.application.command.command_execution_pipeline import CommandExecutionPipeline
from server.application.execution.execution_context import ExecutionContext
from server.application.history.history_store import CommandHistoryStore
from server.application.jobs.background_job_store import BackgroundJobStore
from server.application.tasks.task_runner import WebTaskRunner
from server.application.tasks.task_status import WebTaskStatus
from server.application.tasks.task_store import WebTaskStore
from server.connection.runtime.session_runtime import ClientSessionRuntime
from server.models.records import LifecycleRecordBase, OutputRecordBase
from server.persistence.rch_database import RchDatabase


class RecordBaseRefactorTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(prefix='rch-record-refactor-', suffix='.db')
        os.close(fd)
        os.remove(self.db_path)
        self.database = RchDatabase(self.db_path)

    def tearDown(self):
        self.database.close_thread_connection()
        for suffix in ('', '-wal', '-shm'):
            try:
                os.remove(self.db_path + suffix)
            except FileNotFoundError:
                pass

    def test_base_shapes_do_not_merge_lifecycle_status(self):
        lifecycle = LifecycleRecordBase().to_dict()
        self.assertEqual(
            {
                'machine_id', 'client_id', 'hostname', 'addr',
                'created_at', 'started_at', 'updated_at', 'finished_at',
            },
            set(lifecycle),
        )
        self.assertNotIn('status', lifecycle)
        self.assertNotIn('state', lifecycle)

        output = OutputRecordBase(seq=2, status=1, text='done', eof=1, created_at='t').to_dict()
        self.assertEqual({'seq', 'status', 'text', 'eof', 'created_at'}, set(output))
        self.assertEqual(1, output['eof'])

    def test_task_keeps_lifecycle_fields_without_duplicate_chunks(self):
        store = WebTaskStore()
        session_info = SimpleNamespace(
            machine_id='m1', client_id='c1', hostname='host', addr='127.0.0.1',
        )
        task = store.create_task('c1', 'echo hello', tab_id='tab-1', session_info=session_info)
        self.assertEqual(WebTaskStatus.RUNNING, task['status'])
        self.assertEqual('m1', task['machine_id'])
        self.assertEqual('127.0.0.1', task['addr'])
        self.assertTrue(task['created_at'])
        self.assertTrue(task['started_at'])
        self.assertTrue(task['updated_at'])
        self.assertEqual('', task['finished_at'])
        self.assertNotIn('chunks', task)

    def test_history_does_not_persist_empty_eof_only_chunk_and_derives_summary(self):
        store = CommandHistoryStore(self.database)
        conn = SimpleNamespace(session_info=SimpleNamespace(
            machine_id='m1', client_id='c1', hostname='host', addr='127.0.0.1', cwd='/start',
        ))
        entry_id = store.create_entry_for_connection(conn, 'echo hello', source='web')
        store.append_output_for_connection(conn, entry_id, 1, 'hello', eof=0)
        store.append_output_for_connection(conn, entry_id, 1, '', eof=1)
        store.update_entry_status_for_connection(conn, entry_id, 'success', cwd_end='/end')

        entry = store._get_entry('m1', entry_id)
        self.assertEqual(2, entry['output_chunk_count'])
        self.assertEqual(1, len(entry['output_records']))
        self.assertEqual(0, entry['output_records'][-1]['eof'])
        self.assertEqual('hello', entry['output_records'][-1]['text'])
        self.assertEqual('success', entry['status'])
        self.assertEqual('/start', entry['cwd_start'])
        self.assertEqual('/end', entry['cwd_end'])
        for removed in (
            'duration_ms', 'final_status', 'has_output', 'output_summary',
            'output_stored_char_count', 'output_record_seq', 'has_files', 'file_count',
        ):
            self.assertNotIn(removed, entry)

        view = store.view_service.get_execution_history_page('m1', limit=10)['items'][0]
        self.assertEqual('hello', view['output_summary'])

        quick = store.view_service.get_history_by_machine_id('m1')[0]
        self.assertTrue(quick['last_used_at'])
        self.assertEqual('hello', quick['output_summary'])

    def test_history_keeps_eof_on_nonempty_output_record(self):
        store = CommandHistoryStore(self.database)
        conn = SimpleNamespace(session_info=SimpleNamespace(
            machine_id='m1', client_id='c1', hostname='host', addr='127.0.0.1', cwd='/start',
        ))
        entry_id = store.create_entry_for_connection(conn, 'printf done', source='web')
        store.append_output_for_connection(conn, entry_id, 1, 'done', eof=1)

        entry = store._get_entry('m1', entry_id)
        self.assertEqual(1, len(entry['output_records']))
        self.assertEqual('done', entry['output_records'][0]['text'])
        self.assertEqual(1, entry['output_records'][0]['eof'])

    def test_raw_session_result_stream_uses_eof_only_to_end_stream(self):
        runtime = ClientSessionRuntime()
        runtime.message_queue.put(1, 'done', 1)
        connection = SimpleNamespace(
            context=SimpleNamespace(command_history_orchestrator=None, script_grant_service=None),
            session_info=SimpleNamespace(client_id='c1'),
        )

        # Keep the original execution contract: EOF terminates the low-level
        # command stream but is not propagated into the upper-layer tuple.
        self.assertEqual([(1, 'done')], list(runtime.wait_for_result(connection, 7, 'echo done')))

    def test_command_pipeline_does_not_promote_eof_into_event_payload(self):
        class _Executor:
            @staticmethod
            def process_command(command, history_entry_id=''):
                del command, history_entry_id

                def _result_iter():
                    # The pipeline intentionally consumes only status/result.
                    # Normal runtime output is a two-tuple, matching the original contract.
                    yield 1, 'done'

                return _result_iter

        pipeline = CommandExecutionPipeline(command_history_orchestrator=None)
        context = ExecutionContext(session=SimpleNamespace(), command='echo done')
        events = list(pipeline.iter_events(context, _Executor(), finalize_history=False))
        chunk = next(event for event in events if event.event_type == CommandExecutionEvent.CHUNK)
        self.assertNotIn('eof', chunk.payload)

    def test_task_history_append_keeps_original_default_eof(self):
        published = []
        history_calls = []

        class _EventBus:
            def publish(self, name, payload, **kwargs):
                published.append((name, dict(payload), dict(kwargs)))

        class _History:
            def append_output(self, *args):
                history_calls.append(args)

        class _TaskStore:
            def get_task(self, task_id):
                return {'task_id': task_id, 'tab_id': 'tab-1'}

        server = SimpleNamespace(command_history_orchestrator=_History())
        runner = WebTaskRunner(server, _EventBus(), _TaskStore(), None, None)
        session = SimpleNamespace(get_foreground_task=lambda: {})
        context = SimpleNamespace(
            task_id='task-1', client_id='c1', command='echo done', command_id=3,
            metadata={}, tab_id='tab-1', history_entry_id='history-1', session=session,
        )

        runner._publish_stream_chunk(context, 1, 'done')

        self.assertEqual('command_result', published[0][0])
        self.assertNotIn('eof', published[0][1])
        self.assertEqual(0, history_calls[0][-1])

    def test_job_counts_are_derived_and_messages_use_output_record_shape(self):
        store = BackgroundJobStore(self.database)
        base = {
            'client_id': 'c1',
            'machine_id': 'm1',
            'hostname': 'host',
            'addr': '127.0.0.1',
            'job_id': 'job-1',
            'job_name': 'DemoJob',
            'job_key': 'demo',
            'thread_name': 'Thread-1',
            'execution_mode': 'inproc',
            'time': '2026-10-02T20:00:00',
        }
        store.apply_status_report({**base, 'state': 'running'})
        store.append_message_report({**base, 'time': '2026-10-02T20:00:01', 'status': 1, 'text': '', 'eof': 1})
        store.append_file_report({**base, 'time': '2026-10-02T20:00:02', 'file': {'artifact_id': 'a1'}})
        store.apply_status_report({**base, 'time': '2026-10-02T20:00:03', 'state': 'stopped'})

        summary = store.list_raw_jobs(machine_id='m1')[0]
        self.assertEqual(1, summary['message_count'])
        self.assertEqual(1, summary['file_count'])
        self.assertNotIn('last_message', summary)
        self.assertNotIn('display_name', summary)
        self.assertEqual('2026-10-02T20:00:03', summary['finished_at'])
        self.assertEqual('127.0.0.1', summary['addr'])

        detail = store.get_raw_job('job-1', machine_id='m1')
        self.assertEqual(
            {'seq', 'status', 'text', 'eof', 'created_at'},
            set(detail['messages'][0]),
        )
        self.assertEqual(1, detail['messages'][0]['eof'])
        self.assertEqual('2026-10-02T20:00:01', detail['messages'][0]['created_at'])
        self.assertEqual('2026-10-02T20:00:02', detail['files'][0]['created_at'])

        columns = {
            row['name']
            for row in self.database.connection().execute('PRAGMA table_info(background_jobs)').fetchall()
        }
        self.assertNotIn('message_count', columns)
        self.assertNotIn('file_count', columns)
        self.assertNotIn('last_message', columns)
        self.assertNotIn('display_name', columns)
        self.assertIn('finished_at', columns)

    def test_job_file_snapshot_survives_removed_artifact(self):
        store = BackgroundJobStore(self.database)
        base = {
            'client_id': 'c1', 'machine_id': 'm1', 'hostname': 'host', 'addr': '127.0.0.1',
            'job_id': 'job-removed-file', 'job_name': 'DemoJob', 'job_key': 'demo',
            'thread_name': 'Thread-1', 'execution_mode': 'inproc', 'time': '2026-10-02T20:00:00',
        }
        store.apply_status_report({**base, 'state': 'running'})
        store.append_file_report({
            **base,
            'time': '2026-10-02T20:00:01',
            'file': {
                'artifact_id': 'gone-1',
                'artifact_type': 'files',
                'original_name': 'report.txt',
                'stored_name': 'report_hash.txt',
                'relative_path': '/artifacts/report_hash.txt',
                'size': 123,
                'download_url': '/api/artifacts/gone-1/download',
            },
        })

        class _MissingArtifactService:
            @staticmethod
            def get_artifact_by_id(artifact_id):
                raise FileNotFoundError(artifact_id)

        store.artifact_service = _MissingArtifactService()
        detail = store.get_job_for_scope('job-removed-file', machine_id='m1')
        file_item = detail['files'][0]
        self.assertEqual('report.txt', file_item['original_name'])
        self.assertEqual('report_hash.txt', file_item['stored_name'])
        self.assertEqual(123, file_item['size'])
        self.assertFalse(file_item['is_available'])
        self.assertEqual('Artifact removed', file_item['status_text'])

    def test_current_schema_contains_only_canonical_record_fields(self):
        conn = self.database.connection()
        history_columns = {
            row['name']
            for row in conn.execute('PRAGMA table_info(command_executions)').fetchall()
        }
        self.assertTrue({
            'machine_id', 'client_id', 'hostname', 'addr',
            'created_at', 'started_at', 'updated_at', 'finished_at',
            'output_line_count', 'output_chunk_count', 'output_char_count',
            'output_truncated', 'output_records_json', 'files_json',
        }.issubset(history_columns))
        for removed in (
            'time_text', 'duration_ms', 'final_status', 'has_output', 'output_summary',
            'output_stored_char_count', 'output_record_seq', 'has_files', 'file_count',
            'finished_at_ms',
        ):
            self.assertNotIn(removed, history_columns)

        message_columns = {
            row['name']
            for row in conn.execute('PRAGMA table_info(background_job_messages)').fetchall()
        }
        self.assertIn('eof', message_columns)
        self.assertIn('created_at', message_columns)
        self.assertNotIn('event_time', message_columns)

        file_columns = {
            row['name']
            for row in conn.execute('PRAGMA table_info(background_job_files)').fetchall()
        }
        self.assertIn('created_at', file_columns)
        self.assertIn('snapshot_json', file_columns)
        self.assertNotIn('event_time', file_columns)


if __name__ == '__main__':
    unittest.main()
