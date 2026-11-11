import json
import os
from datetime import datetime

from core.artifact_contract import ArtifactSourceKind
from core.utils.artifact_naming import build_artifact_filename, build_command_name, clean_artifact_label


class CommandOutputArtifactService:
    ARTIFACT_TYPE = 'command_output'

    DEFAULT_CATEGORY = 'command_output'
    SCRIPT_CATEGORY = 'script_output'
    JOB_CATEGORY = 'job_output'


    def __init__(self, artifact_service):
        self.artifact_service = artifact_service

    def _now(self):
        return datetime.now()

    def _normalize_category(self, category: str) -> str:
        normalized = str(category or '').strip()
        return normalized or self.DEFAULT_CATEGORY

    def _normalize_output_format(self, output_format: str) -> str:
        normalized = str(output_format or 'text').strip().lower() or 'text'
        if normalized not in {'text', 'json'}:
            raise ValueError('output_format must be text or json')
        return normalized

    @staticmethod
    def _raw_output_name(name: str) -> str:
        leaf = str(name or '').strip().replace('\\', '/').rsplit('/', 1)[-1]
        if leaf.lower().endswith('.py'):
            leaf = leaf[:-3]
        return clean_artifact_label(leaf, max_length=48)

    def build_output_name(self, *, category: str, source_command: str, now=None, output_format: str = 'text',
                         output_name_prefix: str = '') -> str:
        current_time = now or self._now()
        normalized_category = self._normalize_category(category)
        normalized_format = self._normalize_output_format(output_format)
        normalized_format_extension = 'json' if normalized_format == 'json' else 'txt'
        if output_name_prefix:
            return build_artifact_filename(output_name_prefix, normalized_format_extension, now=current_time)

        if normalized_category == self.JOB_CATEGORY:
            return build_artifact_filename('job_output', 'json', now=current_time,
                                           label=self._raw_output_name(source_command))
        if normalized_category == self.SCRIPT_CATEGORY:
            return build_artifact_filename('script', normalized_format_extension, now=current_time,
                                           label=self._raw_output_name(source_command))
        return build_artifact_filename('command_output', normalized_format_extension, now=current_time,
                                       label=build_command_name(source_command))

    def _resolve_script_output_name_source(self, *, extra: dict | None = None) -> str:
        # The execution display command and script display_name are not file identifiers.
        payload = extra if isinstance(extra, dict) else {}
        return str(payload.get('script_name') or '').strip()

    def build_extra(self, *, source: str, source_command: str, extra: dict | None = None, saved_at=None) -> dict:
        payload = dict(extra or {})
        current_time = saved_at or self._now()

        payload.update({
            'source': str(source or payload.get('source') or 'command_output_save').strip(),
            'saved_at': current_time.isoformat(timespec='seconds'),
        })

        # script output 只保留 script_name/script_path/params，不把展示用命令写进 meta。
        resolved_source_command = str(source_command or payload.get('source_command') or '').strip()
        if resolved_source_command:
            payload['source_command'] = resolved_source_command

        return payload

    def allocate_output_path(self, *, category: str, machine_id: str, source_command: str, now=None,
                             output_format: str = 'text', output_name_prefix: str = '') -> dict:
        normalized_category = self._normalize_category(category)
        output_name = self.build_output_name(
            category=normalized_category,
            source_command=source_command,
            now=now,
            output_format=output_format,
            output_name_prefix=output_name_prefix,
        )

        allocation = self.artifact_service.allocate_artifact_path(
            artifact_type=self.ARTIFACT_TYPE,
            machine_id=machine_id,
            original_name=output_name,
        )

        allocation['original_name'] = output_name
        return allocation

    def register_output_artifact(self, *, allocation: dict, category: str, hostname: str, machine_id: str,
                                 client_id: str = '', addr: str = '', source: str = '',
                                 source_command: str = '', source_command_id=None,
                                 job_id: str = '', job_name: str = '', job_key: str = '',
                                 extra: dict | None = None, saved_at=None) -> dict:
        normalized_category = self._normalize_category(category)
        merged_extra = self.build_extra(
            source=source,
            source_command=source_command,
            extra=extra,
            saved_at=saved_at,
        )

        return self.artifact_service.register_existing_artifact(
            artifact_type=self.ARTIFACT_TYPE,
            source_kind=ArtifactSourceKind.COMMAND_OUTPUT.value,
            hostname=(hostname or '').strip() or 'unknown_host',
            machine_id=allocation.get('machine_id') or (machine_id or '').strip() or 'unknown_machine',
            original_name=allocation.get('original_name') or os.path.basename(allocation.get('file_path', '')) or 'cmd_output.txt',
            file_path=allocation['file_path'],
            stored_name=allocation['stored_name'],
            source_command_id=source_command_id,
            client_id=client_id,
            addr=addr,
            job_id=job_id,
            job_name=job_name,
            job_key=job_key,
            extra=merged_extra,
        )

    def save_text_output(self, *, content: str, category: str, hostname: str, machine_id: str,
                         client_id: str = '', addr: str = '', source: str = '',
                         source_command: str = '', source_command_id=None,
                         job_id: str = '', job_name: str = '', job_key: str = '',
                         extra: dict | None = None, output_format: str = 'text') -> dict:
        now = self._now()
        normalized_category = self._normalize_category(category)
        normalized_format = self._normalize_output_format(output_format)
        content_text = '' if content is None else str(content)
        if normalized_format == 'json':
            try:
                json.loads(content_text)
            except (TypeError, ValueError) as error:
                raise ValueError('JSON output must contain valid JSON') from error

        allocation_name_source = source_command
        if normalized_category == self.JOB_CATEGORY:
            allocation_name_source = job_name
        elif normalized_category == self.SCRIPT_CATEGORY:
            allocation_name_source = self._resolve_script_output_name_source(extra=extra)

        extra_payload = extra if isinstance(extra, dict) else {}
        is_terminal_toolbar_export = (
            normalized_category == self.DEFAULT_CATEGORY
            and (
                str(source or '').strip() == 'terminal_toolbar_action'
                or str(extra_payload.get('saved_from') or '').strip() == 'terminal_toolbar'
            )
        )
        is_pty_toolbar_export = (
            normalized_category == self.DEFAULT_CATEGORY
            and (str(source or '').strip() == 'pty_toolbar_action'
                 or str(extra_payload.get('saved_from') or '').strip() == 'pty_toolbar')
        )
        allocation = self.allocate_output_path(
            category=normalized_category,
            machine_id=machine_id,
            source_command=allocation_name_source,
            now=now,
            output_format=normalized_format,
            output_name_prefix=('pty_output' if is_pty_toolbar_export else
                                'terminal_output' if is_terminal_toolbar_export else ''),
        )

        with open(allocation['file_path'], 'w', encoding='utf-8', errors='replace') as file_obj:
            file_obj.write(content_text)

        return self.register_output_artifact(
            allocation=allocation,
            category=normalized_category,
            hostname=hostname,
            machine_id=machine_id,
            client_id=client_id,
            addr=addr,
            source=source,
            source_command=source_command,
            source_command_id=source_command_id,
            job_id=job_id,
            job_name=job_name,
            job_key=job_key,
            extra=extra,
            saved_at=now,
        )