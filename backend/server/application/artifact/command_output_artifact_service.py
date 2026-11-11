"""Register terminal, script, and job output with one Saved metadata contract."""

import json
import os
from datetime import datetime

from core.artifact_contract import ArtifactCategory
from core.utils.artifact_naming import build_artifact_filename, build_command_name, clean_artifact_label


class CommandOutputArtifactService:
    ARTIFACT_TYPE = 'command_output'
    OUTPUT_KINDS = frozenset({'command', 'script', 'job'})
    SAVED_FROM = frozenset({
        'saveout', 'terminal_output', 'terminal_json_viewer',
        'terminal_toolbar', 'pty_toolbar', 'background_job_detail',
    })
    EXTRA_FIELDS = frozenset({
        'saved_from', 'source_command', 'script_path',
        'started_at', 'finished_at', 'final_status',
    })

    def __init__(self, artifact_service):
        self.artifact_service = artifact_service

    def _now(self):
        return datetime.now()

    @classmethod
    def _output_kind(cls, kind):
        kind = str(kind or '').strip()
        if kind not in cls.OUTPUT_KINDS:
            raise ValueError('output_kind must be command, script or job')
        return kind

    @staticmethod
    def _output_format(fmt):
        fmt = str(fmt or '').strip().lower()
        if fmt not in {'text', 'json'}:
            raise ValueError('output_format must be text or json')
        return fmt

    @staticmethod
    def _source_name(value):
        leaf = str(value or '').strip().replace('\\', '/').rsplit('/', 1)[-1]
        if leaf.endswith('.py'):
            leaf = leaf[:-3]
        return clean_artifact_label(leaf, max_length=48)

    def build_output_name(self, *, output_kind: str, source_command: str, now=None,
                          output_format: str = 'text', script_path: str = '', job_key: str = '',
                          saved_from: str = ''):
        kind = self._output_kind(output_kind)
        ext = 'json' if self._output_format(output_format) == 'json' else 'txt'
        if saved_from == 'pty_toolbar':
            return build_artifact_filename('pty_output', ext, now=now)
        if saved_from == 'terminal_toolbar':
            return build_artifact_filename('terminal_output', ext, now=now)
        if kind == 'script':
            label = self._source_name(script_path)
            if not label:
                raise ValueError('script_path is required for script output')
            return build_artifact_filename('script', ext, now=now, label=label)
        if kind == 'job':
            label = self._source_name(job_key)
            if not label:
                raise ValueError('job_key is required for job output')
            return build_artifact_filename('job_output', ext, now=now, label=label)
        return build_artifact_filename('command_output', ext, now=now,
                                       label=build_command_name(source_command))

    def build_extra(self, *, source_command: str, extra: dict | None = None):
        supplied = dict(extra or {})
        unexpected = set(supplied) - self.EXTRA_FIELDS
        if unexpected:
            raise ValueError(f'Unsupported output metadata fields: {", ".join(sorted(unexpected))}')
        saved_from = str(supplied.get('saved_from') or '').strip()
        if saved_from not in self.SAVED_FROM:
            raise ValueError('saved_from must identify a supported output save action')
        result = {'saved_from': saved_from}
        command = str(source_command or supplied.get('source_command') or '').strip()
        if command:
            result['source_command'] = command
        for key in ('script_path', 'started_at', 'finished_at', 'final_status'):
            value = str(supplied.get(key) or '').strip()
            if value:
                result[key] = value
        return result

    def allocate_output_path(self, *, output_kind: str, machine_id: str, source_command: str,
                             now=None, output_format='text', script_path='', job_key='', saved_from=''):
        name = self.build_output_name(
            output_kind=output_kind, source_command=source_command, now=now,
            output_format=output_format, script_path=script_path,
            job_key=job_key, saved_from=saved_from,
        )
        allocation = self.artifact_service.allocate_artifact_path(
            artifact_type=self.ARTIFACT_TYPE, machine_id=machine_id, original_name=name,
        )
        allocation['original_name'] = name
        return allocation

    def register_output_artifact(self, *, allocation: dict, output_kind: str, hostname: str, machine_id: str,
                                 client_id='', addr='', source_command='', source_command_id=None,
                                 extra=None):
        self._output_kind(output_kind)
        metadata = self.build_extra(source_command=source_command, extra=extra)
        category = (ArtifactCategory.TERMINAL_LOGS.value
                    if metadata['saved_from'] in {'terminal_toolbar', 'pty_toolbar'}
                    else ArtifactCategory.COMMAND_OUTPUT.value)
        return self.artifact_service.register_existing_artifact(
            artifact_type=self.ARTIFACT_TYPE,
            category=category,
            hostname=str(hostname or '').strip() or 'unknown_host',
            machine_id=allocation.get('machine_id') or str(machine_id or '').strip() or 'unknown_machine',
            original_name=allocation.get('original_name') or os.path.basename(allocation.get('file_path', '')),
            file_path=allocation['file_path'],
            stored_name=allocation['stored_name'],
            source_command_id=source_command_id,
            client_id=client_id, addr=addr, extra=metadata,
        )

    def save_text_output(self, *, content: str, output_kind: str, hostname: str, machine_id: str,
                         client_id='', addr='', source_command='', source_command_id=None,
                         job_key='', extra=None, output_format='text'):
        now = self._now()
        kind = self._output_kind(output_kind)
        fmt = self._output_format(output_format)
        metadata = self.build_extra(source_command=source_command, extra=extra)
        text = '' if content is None else str(content)
        if fmt == 'json':
            try:
                json.loads(text)
            except (TypeError, ValueError) as exc:
                raise ValueError('JSON output must contain valid JSON') from exc
        allocation = self.allocate_output_path(
            output_kind=kind, machine_id=machine_id, source_command=source_command,
            now=now, output_format=fmt, script_path=metadata.get('script_path', ''),
            job_key=job_key, saved_from=metadata['saved_from'],
        )
        with open(allocation['file_path'], 'w', encoding='utf-8', errors='replace') as handle:
            handle.write(text)
        try:
            return self.register_output_artifact(
                allocation=allocation, output_kind=kind, hostname=hostname, machine_id=machine_id,
                client_id=client_id, addr=addr, source_command=source_command,
                source_command_id=source_command_id, extra=metadata,
            )
        except Exception:
            os.remove(allocation['file_path'])
            raise
