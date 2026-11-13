"""Domain dispatch for structured one-shot Client operations."""

import json

from client.jobs.command_control import ClientJobControl


class ClientControlDispatcher:
    # Only this registry knows which domain provides a Control handler.
    _handlers = {}

    @classmethod
    def register(cls, domain, handler):
        cls._handlers[domain] = handler

    @classmethod
    def execute(cls, commands, domain, action, payload):
        from core.protocol.control import validate_control_fields
        validate_control_fields(domain, action, payload)
        handler = cls._handlers.get(domain)
        if handler is None:
            return 0, f'Unsupported Control domain: {domain}'
        return handler(commands, action, payload)


class ClientRemoteFilesControl:
    # The existing filesystem handlers remain the single implementation of
    # path resolution, validation, archive policies and cancellation.
    _actions = {
        'browse_directory': ('browse_dir', True),
        'create_directory': ('mkdir_path', False),
        'rename_path': ('rename_path', False),
        'delete_paths': ('delete_paths', True),
        'paste_paths': ('paste_paths', True),
        'create_archive': ('create_zip_paths', True),
        'peek_archive': ('peek_zip', True),
        'read_archive_entry': ('read_zip_entry', True),
        'extract_archive': ('extract_zip_path', True),
        'inspect_upload': ('inspect_remote_upload', True),
        'save_file': ('save_file_content', False),
    }

    @classmethod
    def execute(cls, commands, action, payload):
        spec = cls._actions.get(action)
        if spec is None:
            return 0, f'Unsupported remote_files Control action: {action}'
        method_name, structured = spec
        status, result = getattr(commands, method_name)(payload)
        if status == 1 and structured and isinstance(result, str):
            try:
                result = json.loads(result)
            except (ValueError, TypeError):
                return 0, 'Invalid remote file result'
            if not isinstance(result, dict):
                return 0, 'Invalid remote file result'
        return status, result


class ClientScriptControl:
    @staticmethod
    def execute(commands, action, payload):
        if action != 'run':
            return 0, f'Unsupported script Control action: {action}'
        source = payload.get('source')
        params = payload.get('params')
        name = payload.get('script_name')
        if not isinstance(source, str) or not source.strip() or not isinstance(params, dict) or not isinstance(name, str) or not name.strip():
            return 0, 'Invalid script Control payload'
        return commands.execute_script_stream(source, kwargs={**params, '__script_name__': name})


ClientControlDispatcher.register('job', ClientJobControl.execute)
ClientControlDispatcher.register('remote_files', ClientRemoteFilesControl.execute)
ClientControlDispatcher.register('script', ClientScriptControl.execute)
