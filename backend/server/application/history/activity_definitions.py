"""Canonical Activity identities and summaries for UI operations."""
from dataclasses import dataclass
from core.protocol.control import ControlDomain, JobAction, RemoteFilesAction, ClipboardAction, ConfigurationAction, ProcessAction, WatchdogAction


@dataclass(frozen=True)
class ActivityOperation:
    kind: str
    action: str
    arguments: dict
    origin: str = 'web_ui'
    presentation: str = 'none'
    text: str = ''
    target: str = ''
    reuse_origin: bool = False

    def invocation(self):
        return {'command': self.text} if self.text else {}

    def display_summary(self):
        return operation_summary(self.kind, self.action, self.arguments, self.text, self.target)


class ActivityKind:
    COMMAND = 'command'
    ALIAS = 'alias'
    TRANSFER = 'transfer'
    EXTERNAL_TOOL = 'external_tool'
    PTY = 'pty'
    SCREEN_VIEW = 'screen_view'
    SESSION_KINDS = (PTY, SCREEN_VIEW)
    ALL = (COMMAND, ALIAS, TRANSFER, EXTERNAL_TOOL, PTY, SCREEN_VIEW, *ControlDomain)


class ActivityAction:
    INVOKE = 'invoke'
    SESSION = 'session'
    SET_TEXT = 'set_text'
    SET_IMAGE = 'set_image'
    SET_FILES = 'set_files'
    SET_ARTIFACT_FILE = 'set_artifact_file'


def process_arguments(pid, name):
    return {'pid': int(pid), 'name': ' '.join(str(name or '').split())[:160]}


def ui_activity_summary(kind, action, args):
    """One source of user-facing summary rules for the tracked UI actions."""
    if kind in ActivityKind.SESSION_KINDS:
        return ('PTY' if kind == ActivityKind.PTY else 'Screen View') + (
            ' · ' + str(args['shell']) if kind == ActivityKind.PTY and args.get('shell') else '')
    if kind == ControlDomain.CLIPBOARD:
        if action == ClipboardAction.GET:
            return 'Get clipboard'
        action = args.get('format_action') or action
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
    if kind == ControlDomain.PROCESS:
        name = str(args.get('name') or '').strip()
        return ('Kill app ' if args.get('target_type') == 'app' else 'Kill process ') + (
            name + ' ' if name else '') + f"(PID {args.get('pid') or '?'})"
    return None


def operation_summary(kind, action, args, command='', target=''):
    """Display label for the existing Activity list; request facts remain untouched."""
    if kind == ControlDomain.SCRIPT:
        return str(target or args.get('script_name') or command or 'Script')
    summary = ui_activity_summary(kind, action, args)
    if summary is not None:
        return summary
    if kind == ActivityKind.ALIAS:
        return str(target or command or 'Alias')
    if kind == ActivityKind.COMMAND:
        return ' '.join(str(command or '-').split())[:160]
    if kind == ControlDomain.REMOTE_FILES:
        count = args.get('count') or len(args.get('paths') or []) or 1
        noun = 'item' if count == 1 else 'items'
        actions = {
            RemoteFilesAction.CREATE_DIRECTORY: 'Create directory',
            RemoteFilesAction.DELETE_PATHS: f'Delete {count} {noun}',
            RemoteFilesAction.RENAME_PATH: 'Rename',
            RemoteFilesAction.PASTE_PATHS: f"{'Move' if args.get('operation') == 'move' else 'Copy'} {count} {noun}",
            RemoteFilesAction.BROWSE_DIRECTORY: 'Browse directory',
            RemoteFilesAction.PEEK_ARCHIVE: 'Inspect archive',
            RemoteFilesAction.READ_ARCHIVE_ENTRY: 'Read archive entry',
            RemoteFilesAction.INSPECT_UPLOAD: 'Inspect upload',
            RemoteFilesAction.CREATE_ARCHIVE: f'Create archive from {count} {noun}',
            RemoteFilesAction.EXTRACT_ARCHIVE: f"Extract archive {args.get('path') or ''}",
            RemoteFilesAction.SAVE_FILE: f"Save file {args.get('path') or ''}",
        }
        return ('Inspect · ' if args.get('inspect') else '') + actions.get(action, action or 'Remote Files')
    if kind == ActivityKind.TRANSFER:
        name = str(args.get('filename') or args.get('path') or '').replace('\\', '/').split('/')[-1]
        count = args.get('count') or 1
        return f"{'Upload' if action == 'upload_files' else 'Download'} {str(count) + ' items' if count > 1 else name or 'file'}"
    if kind == ControlDomain.JOB:
        name = args.get('job_name') or args.get('job_key') or 'job'
        if action == JobAction.STOP_ALL:
            return 'Stop all jobs'
        if action == JobAction.PS:
            return 'List jobs'
        if action == JobAction.STATUS:
            return f'Job status · {name}'
        return f"{'Start' if action == JobAction.START else 'Stop'} {name}"
    if kind == ControlDomain.CONFIGURATION:
        label = {ConfigurationAction.GET: 'Get configuration', ConfigurationAction.SET: 'Set', ConfigurationAction.RESET: 'Reset'}.get(action, 'Configuration')
        return f"{label} {args.get('key') or ''}".strip()
    if kind == ControlDomain.WATCHDOG:
        return 'Watchdog status'
    if kind == ActivityKind.EXTERNAL_TOOL:
        actions = {
            'install_package': 'Install', 'uninstall_package': 'Uninstall',
            'clear_package_cache': 'Clear cache', 'start_instance': 'Start',
            'create_instance': 'Create', 'restart_instance': 'Restart',
            'run_oneshot': 'Run', 'exec': 'Run', 'stop_instance': 'Stop',
            'remove_instance': 'Remove', 'clear_instance_logs': 'Clear logs',
            'get_install_statuses': 'Check installation', 'resolve_launcher': 'Resolve launcher',
            'read_instance': 'Read instance', 'read_instance_logs': 'Read logs',
            'list_instances': 'List instances', 'preview_instance': 'Preview',
        }
        tools = args.get('tools') if isinstance(args.get('tools'), list) else []
        first = tools[0] if len(tools) == 1 and isinstance(tools[0], dict) else {}
        target = (args.get('exec_name') or args.get('tool_id') or args.get('package_id') or
                  first.get('tool_id') or first.get('package_id') or '')
        if not target and len(tools) > 1:
            target = f'{len(tools)} tools'
        instance = f" ({args['instance_id']})" if args.get('instance_id') else ''
        return f"{actions.get(action, 'External Tool')}{' ' + str(target) if target else ''}{instance}"
    return action or kind or 'Activity'


def activity_summary(entry):
    return entry.get('summary') or entry['action'] or entry['kind']
