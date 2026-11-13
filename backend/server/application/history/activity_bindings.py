"""Declarative semantic operation definitions used when assembling application services."""
import shlex

from server.application.history.activity_definitions import ActivityKind, ActivityOperation, process_arguments


def _build(kind, action, args, data, *, origin='web_ui'):
    return ActivityOperation(kind, action, args, data.get('origin') or origin,
                             resolved={'command_type': 'job_control' if kind == ActivityKind.BACKGROUND_JOB else 'command'})


def remote_file_bindings():
    kind = ActivityKind.REMOTE_FILES
    return {
        'create_directory': lambda a: _build(kind, 'create_directory', {'path': a['path']}, a),
        'rename_path': lambda a: _build(kind, 'rename_files', {
            'old_path': a['old_path'], 'new_name': a['new_name'], 'count': 1,
        }, a),
        'create_zip_from_paths': lambda a: _build(kind, 'create_archive', {
            'paths': a['paths'], 'count': len(a['paths']),
            'destination_dir': a['destination_dir'], 'archive_name': a['archive_name'],
        }, a),
        'extract_zip': lambda a: None if a['inspect'] else _build(kind, 'extract_archive', {
            'path': a['path'], 'destination_dir': a['destination_dir'],
            **({'entry_name': a['entry_name']} if a['entry_name'] else {}),
            'conflict_policy': a['conflict_policy'] or 'stop',
        }, a),
        'delete_paths': lambda a: _build(kind, 'delete_files', {
            'paths': a['paths'], 'count': len(a['paths']),
        }, a),
        'paste_paths': lambda a: None if a['inspect'] else _build(kind,
            'copy_files' if a['operation'] == 'copy' else 'move_files', {
                'paths': a['paths'], 'count': len(a['paths']), 'destination_dir': a['destination_dir'],
            }, a),
        'save_file_content': lambda a: _build(kind, 'save_file', {
            'path': a['path'], 'encoding': a['encoding'],
        }, a),
    }


def job_bindings():
    kind = ActivityKind.BACKGROUND_JOB
    return {
        'start_job': lambda a: _build(kind, 'start_job', {
            'job_name': a['job_name'], 'execution_mode': a['execution_mode'],
        }, a, origin='web_api'),
        'stop_job': lambda a: _build(kind, 'stop_job', {'job_key': a['job_key']}, a, origin='web_api'),
    }


def external_tool_bindings():
    kind = ActivityKind.EXTERNAL_TOOL
    operations = {
        'install_client_tool': 'install_package',
        'uninstall_client_tool': 'uninstall_package',
        'clear_client_package_cache': 'clear_package_cache',
        'start_client_instance': 'start_instance',
        'run_client_oneshot': 'run_oneshot',
        'stop_client_instance': 'stop_instance',
        'remove_client_instance': 'remove_instance',
        'clear_client_logs': 'clear_instance_logs',
    }
    return {method: (lambda a, action=action: _build(kind, action, {
        key: a[key] for key in ('tool_id', 'package_id', 'instance_id') if a.get(key)
    }, a, origin='web_api')) for method, action in operations.items()}


def process_bindings():
    kind = ActivityKind.PROCESS
    return {
        action: (lambda a, action=action: ActivityOperation(kind, action,
            process_arguments(a['pid'], a['name']), a.get('origin') or 'web_ui',
            resolved={'command_type': 'control'}))
        for action in ('kill_process', 'kill_app')
    }


def xt_cli_mutation(command, *, origin='cli', presentation='terminal'):
    """Describe a mutating xt Builtin without teaching the execution service about xt."""
    try:
        tokens = shlex.split(str(command or ''))
    except ValueError:
        return None
    if len(tokens) < 3 or tokens[0].lower() != 'xt':
        return None
    group, verb = tokens[1].lower(), tokens[2].lower()
    if group == 'package' and verb in ('install', 'uninstall'):
        if len(tokens) < 4:
            return None
        action = {'install': 'install_package', 'uninstall': 'uninstall_package'}[verb]
        args = {'package_id': tokens[3]}
    elif group == 'instance' and verb in ('create', 'start', 'stop', 'restart'):
        if len(tokens) < 4:
            return None
        action = {'create': 'create_instance', 'start': 'start_instance',
                  'stop': 'stop_instance', 'restart': 'restart_instance'}[verb]
        args = {}
        if verb == 'create':
            args['tool_id'] = tokens[3]
            if '--id' in tokens:
                index = tokens.index('--id') + 1
                if index < len(tokens):
                    args['instance_id'] = tokens[index]
        else:
            args['instance_id'] = tokens[-1]
            if len(tokens) >= 5:
                args['tool_id'] = tokens[3]
    else:
        return None
    return ActivityOperation(ActivityKind.EXTERNAL_TOOL, action, args,
                             origin=origin, presentation=presentation, text=command)
