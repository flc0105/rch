import json
import os
import re
from datetime import datetime


class CommandOutputArtifactService:
    ARTIFACT_TYPE = 'command_output'

    DEFAULT_CATEGORY = 'command_output'
    SCRIPT_CATEGORY = 'script_output'
    JOB_CATEGORY = 'job_output'

    OUTPUT_TIME_FORMAT = '%Y%m%d_%H%M%S'
    SECOND_TOKEN_MAX_LENGTH = 10

    WRAPPER_COMMANDS = {
        'acmd',
        'read',
        'exec',
        'shell',
    }

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

    def _get_prefix(self, category: str) -> str:
        normalized_category = self._normalize_category(category)

        if normalized_category == self.SCRIPT_CATEGORY:
            return 'script'

        if normalized_category == self.JOB_CATEGORY:
            return 'job'

        return 'cmd'

    def _clean_label_part(self, value: str) -> str:
        text = str(value or '').strip().lower()
        text = re.sub(r'[^a-z0-9]+', '_', text)
        return text.strip('_')

    def _strip_script_display_prefix(self, source_command: str) -> str:
        text = str(source_command or '').strip()
        return re.sub(r'^\[Run Script\]\s*', '', text, flags=re.IGNORECASE).strip()

    def _build_script_label(self, source_command: str) -> str:
        text = self._strip_script_display_prefix(source_command)
        label = self._clean_label_part(text)

        # Script display name 可以完整保留，避免 [Run Script] Get Chrome Tabs 只生成 get。
        return label[:64].strip('_') or 'script'

    def _build_command_label(self, source_command: str) -> str:
        text = self._strip_script_display_prefix(source_command)
        tokens = [
            item
            for item in re.split(r'\s+', text)
            if item
        ]

        if not tokens:
            return 'output'

        first = self._clean_label_part(tokens[0])
        if not first:
            return 'output'

        if first not in self.WRAPPER_COMMANDS or len(tokens) < 2:
            return first

        second = self._clean_label_part(tokens[1])

        # 第二段不足 10 位才保留；过长直接丢弃。
        if second and len(second) < self.SECOND_TOKEN_MAX_LENGTH:
            return f'{first}_{second}'

        return first

    def build_output_name(self, *, category: str, source_command: str, now=None, output_format: str = 'text',
                         output_name_prefix: str = '') -> str:
        current_time = now or self._now()
        normalized_category = self._normalize_category(category)
        normalized_format = self._normalize_output_format(output_format)
        prefix = self._get_prefix(normalized_category)
        timestamp = current_time.strftime(self.OUTPUT_TIME_FORMAT)
        if output_name_prefix:
            clean_prefix = self._clean_label_part(output_name_prefix)
            if not clean_prefix:
                raise ValueError('output_name_prefix must contain a valid filename prefix')
            extension = '.json' if normalized_format == 'json' else '.txt'
            return f'{clean_prefix}_{timestamp}{extension}'

        if normalized_category == self.JOB_CATEGORY:
            label = self._clean_label_part(source_command)[:64].strip('_') or 'output'
            return f'job_output_{timestamp}_{label}.json'

        if normalized_category == self.SCRIPT_CATEGORY:
            label = self._build_script_label(source_command)
        else:
            label = self._build_command_label(source_command)

        extension = '.json' if normalized_format == 'json' else '.txt'
        return f'{prefix}_{timestamp}_{label}{extension}'

    def _resolve_script_output_name_source(self, *, source_command: str, extra: dict | None = None) -> str:
        resolved_source_command = str(source_command or '').strip()
        if resolved_source_command:
            return resolved_source_command

        payload = extra if isinstance(extra, dict) else {}

        # 文件名沿用原 terminal 展示名规则：优先用可见脚本名，不使用脚本路径。
        script_display_name = str(payload.get('script_display_name') or '').strip()
        if script_display_name:
            return script_display_name

        script_name = str(payload.get('script_name') or '').replace('\\', '/').strip()
        if script_name:
            leaf_name = script_name.rsplit('/', 1)[-1]
            return leaf_name[:-3] if leaf_name.endswith('.py') else leaf_name

        return ''

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
            category=normalized_category,
        )

        allocation['original_name'] = output_name
        allocation['category'] = normalized_category
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
            category=normalized_category,
            hostname=(hostname or '').strip() or 'unknown_host',
            machine_id=allocation.get('machine_id') or (machine_id or '').strip() or 'unknown_machine',
            original_name=allocation.get('original_name') or os.path.basename(allocation.get('file_path', '')) or 'cmd_output.txt',
            file_path=allocation['file_path'],
            meta_path=allocation['meta_path'],
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
        if normalized_category == self.SCRIPT_CATEGORY:
            # script 类型的 meta 不再写展示命令，但文件名仍沿用 script_name。
            allocation_name_source = self._resolve_script_output_name_source(
                source_command=source_command,
                extra=extra,
            )

        extra_payload = extra if isinstance(extra, dict) else {}
        is_terminal_toolbar_export = (
            normalized_category == self.DEFAULT_CATEGORY
            and (
                str(source or '').strip() == 'terminal_toolbar_action'
                or str(extra_payload.get('saved_from') or '').strip() == 'terminal_toolbar'
            )
        )
        allocation = self.allocate_output_path(
            category=normalized_category,
            machine_id=machine_id,
            source_command=allocation_name_source,
            now=now,
            output_format=normalized_format,
            output_name_prefix='terminal_output' if is_terminal_toolbar_export else '',
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