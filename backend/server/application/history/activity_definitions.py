"""Canonical Activity identities and summaries for UI operations."""
from dataclasses import dataclass, field
from core.protocol.control import JobAction


@dataclass(frozen=True)
class ActivityOperation:
    kind: str
    action: str
    arguments: dict
    origin: str = 'web_ui'
    presentation: str = 'none'
    text: str = ''
    target: str = ''
    resolved: dict = field(default_factory=dict)
    reuse_origin: bool = False

    def invocation(self):
        result = {'arguments': dict(self.arguments)}
        if self.text:
            result['input'] = self.text
        if self.target:
            result['target'] = self.target
        return result


class ActivityKind:
    COMMAND = 'command'
    ALIAS = 'alias'
    SCRIPT = 'script'
    REMOTE_FILES = 'remote_files'
    TRANSFER = 'transfer'
    EXTERNAL_TOOL = 'external_tool'
    BACKGROUND_JOB = 'background_job'
    PTY = 'pty'
    SCREEN_VIEW = 'screen_view'
    CLIPBOARD = 'clipboard'
    PROCESS = 'process'
    SESSION_KINDS = (PTY, SCREEN_VIEW)
    ALL = (COMMAND, ALIAS, SCRIPT, REMOTE_FILES, TRANSFER, EXTERNAL_TOOL,
           BACKGROUND_JOB, PTY, SCREEN_VIEW, CLIPBOARD, PROCESS)


# Map control-plane actions to user-facing Activity operations in the history layer.
JOB_ACTIVITY_ACTIONS = {JobAction.START: 'start_job', JobAction.STOP: 'stop_job', JobAction.STOP_ALL: 'stop_all_jobs'}


class ActivityAction:
    INVOKE = 'invoke'
    RUN = 'run'
    SESSION = 'session'
    KILL_PROCESS = 'kill_process'
    KILL_APP = 'kill_app'
    SET_TEXT = 'set_text'
    SET_IMAGE = 'set_image'
    SET_FILES = 'set_files'
    SET_ARTIFACT_FILE = 'set_artifact_file'


def process_arguments(pid, name):
    return {'pid': int(pid), 'name': ' '.join(str(name or '').split())[:160]}


def clipboard_arguments(action, value):
    """Retain bounded, displayable metadata; never persist transfer URLs or image bytes."""
    args = value if isinstance(value, dict) else {}
    if action == ActivityAction.SET_TEXT:
        text = str(args.get('text') or '')[:2048]
        return {'text': text, 'length': max(0, int(args.get('length') or 0)),
                'truncated': bool(args.get('truncated'))}
    if action == ActivityAction.SET_IMAGE:
        return {'filename': str(args.get('filename') or '')[:160],
                'mime_type': str(args.get('mime_type') or '')[:100],
                'size_bytes': max(0, int(args.get('size_bytes') or 0))}
    if action in (ActivityAction.SET_FILES, ActivityAction.SET_ARTIFACT_FILE):
        result = {'count': max(0, int(args.get('count') or 0)),
                  'names': [str(x)[:160] for x in (args.get('names') or [])[:20]],
                  'names_truncated': bool(args.get('names_truncated'))}
        if action == ActivityAction.SET_ARTIFACT_FILE:
            result['artifact_id'] = str(args.get('artifact_id') or '')[:128]
        return result
    raise ValueError('Unsupported clipboard Activity action')


def ui_activity_summary(kind, action, args):
    """One source of user-facing summary rules for the tracked UI actions."""
    if kind in ActivityKind.SESSION_KINDS:
        return ('PTY' if kind == ActivityKind.PTY else 'Screen View') + (
            ' · ' + str(args['shell']) if kind == ActivityKind.PTY and args.get('shell') else '')
    if kind == ActivityKind.CLIPBOARD:
        label = {ActivityAction.SET_TEXT: 'Set text', ActivityAction.SET_IMAGE: 'Set image',
                 ActivityAction.SET_FILES: 'Set files',
                 ActivityAction.SET_ARTIFACT_FILE: 'Send Artifact file'}.get(action, 'Set clipboard')
        if action == ActivityAction.SET_TEXT:
            preview = str(args.get('text') or '').replace('\n', ' ').replace('\r', ' ')[:64]
            return f'{label} · {preview}' if preview else label
        if action == ActivityAction.SET_IMAGE:
            return f"{label} · {args['filename']}" if args.get('filename') else label
        if args.get('names'):
            return f"{label} · {', '.join(args['names'][:2])}"
        return label
    if kind == ActivityKind.PROCESS:
        name = str(args.get('name') or '').strip()
        return ('Kill app ' if action == ActivityAction.KILL_APP else 'Kill process ') + (
            name + ' ' if name else '') + f"(PID {args.get('pid') or '?'})"
    return None


def activity_summary(entry):
    kind = entry['kind']
    action = entry['action']
    invocation = entry['invocation']
    if kind == ActivityKind.SCRIPT:
        return str(invocation.get('target') or 'Script')
    summary = ui_activity_summary(kind, action, invocation.get('arguments') or {})
    if summary is not None:
        return summary
    if kind in (ActivityKind.COMMAND, ActivityKind.ALIAS):
        # Show the user invocation, not an internal resolved command or encoded payload.
        return str(invocation.get('input') or invocation.get('target') or kind)
    args = invocation.get('arguments') or {}
    if kind == ActivityKind.REMOTE_FILES:
        actions = {
            'create_directory': 'Create directory', 'delete_files': 'Delete files',
            'rename_files': 'Rename', 'copy_files': 'Copy files',
            'move_files': 'Move files', 'create_archive': 'Create archive',
            'extract_archive': 'Extract archive', 'save_file': 'Save file',
        }
        return actions.get(action, action or 'Remote Files')
    if kind == ActivityKind.TRANSFER:
        return 'Upload files' if action == 'upload_files' else 'Download files' if action == 'download_files' else (action or 'Transfer')
    if kind == ActivityKind.BACKGROUND_JOB:
        labels = {'start_job': 'Start', 'stop_job': 'Stop', 'stop_all_jobs': 'Stop all jobs'}
        return f"{labels.get(action, action or 'Background Job')} {args.get('job_name') or args.get('job_key') or ''}".strip()
    if kind == ActivityKind.EXTERNAL_TOOL:
        actions = {
            'install_package': 'Install', 'uninstall_package': 'Uninstall',
            'clear_package_cache': 'Clear cache', 'start_instance': 'Start',
            'create_instance': 'Create', 'restart_instance': 'Restart',
            'run_oneshot': 'Run', 'run_exec': 'Run', 'stop_instance': 'Stop',
            'remove_instance': 'Remove', 'clear_instance_logs': 'Clear logs',
        }
        target = args.get('exec_name') or args.get('instance_id') or args.get('tool_id') or args.get('package_id') or ''
        return f"{actions.get(action, action or 'External Tool')} {target}".strip()
    return action or kind or 'Activity'

