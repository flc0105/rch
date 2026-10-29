"""Read-only foreground task presentation for the Web client."""


def build_foreground_task_snapshot(session):
    task = session.get_foreground_task()
    if not task:
        return {'state': 'Idle'}

    policy = ''
    command = str(task.get('command') or '').strip()
    if command:
        manifest = getattr(session.session_info, 'command_manifest', None) or []
        matches = [item for item in manifest if isinstance(item, dict)
                   and isinstance(item.get('name'), str)
                   and (command == item['name'] or command.startswith(item['name'] + ' '))]
        if matches:
            policy = max(matches, key=lambda item: len(item['name'])).get('cancel_policy', '')
    cancellable = bool(task.get('task_id') and task.get('web_task')
                       and task.get('command_id') and policy != 'none')
    return {
        'state': 'Cancelling' if task.get('cancel_requested') else 'Running',
        'command': task.get('command', ''),
        'task_type': task.get('task_type', ''),
        'source': task.get('source', ''),
        'task_id': task.get('task_id', ''),
        'command_id': task.get('command_id'),
        'started_at': task.get('started_at', ''),
        'cancel_state': task.get('cancel_state', 'running'),
        'cancel_policy': policy,
        'can_cancel': cancellable and not task.get('cancel_requested'),
    }
