"""Canonical Artifact wire values and Saved Files folders."""
from enum import Enum


class ArtifactType(str, Enum):
    FILES = 'files'
    PREVIEWS = 'previews'
    SHARED_FILES = 'shared_files'
    COMMAND_OUTPUT = 'command_output'


class ArtifactOrigin(str, Enum):
    SCREENSHOT_COMMAND = 'screenshot_command'
    WEBCAM_COMMAND = 'webcam_command'
    SCREEN_VIEW = 'screen_view'
    SCRIPT = 'script'
    JOB = 'job'


class ArtifactScope(str, Enum):
    SAVED = 'saved'
    SHARED = 'shared'
    PREVIEW = 'preview'


class ArtifactSourceKind(str, Enum):
    SCREENSHOTS = 'screenshots'
    WEBCAM = 'webcam'
    DOWNLOADS = 'downloads'
    CLIPBOARD = 'clipboard'
    SCRIPT_FILE = 'script_file'
    JOB_FILE = 'job_file'
    COMMAND_OUTPUT = 'command_output'
    TERMINAL_LOGS = 'terminal_logs'
    INBOX = 'inbox'
    SHARED_UPLOAD = 'shared_upload'
    PREVIEW_CACHE = 'preview_cache'


SAVED_FOLDER_NAMES = {
    ArtifactSourceKind.SCREENSHOTS: 'Screenshots',
    ArtifactSourceKind.WEBCAM: 'Webcam',
    ArtifactSourceKind.DOWNLOADS: 'Downloads',
    ArtifactSourceKind.CLIPBOARD: 'Clipboard',
    ArtifactSourceKind.SCRIPT_FILE: 'Script Files',
    ArtifactSourceKind.JOB_FILE: 'Job Files',
    ArtifactSourceKind.COMMAND_OUTPUT: 'Command Output',
    ArtifactSourceKind.TERMINAL_LOGS: 'Terminal Logs',
    ArtifactSourceKind.INBOX: 'Inbox',
}
SAVED_FOLDER_IDS = {kind: f'{ArtifactScope.SAVED.value}:{kind.value}' for kind in SAVED_FOLDER_NAMES}
SAVED_SOURCE_BY_FOLDER_ID = {folder_id: kind for kind, folder_id in SAVED_FOLDER_IDS.items()}

# Producer hints are parsed at the ingestion boundary. Stored source kinds use
# only the canonical ArtifactSourceKind values, never these producer spellings.
PRODUCER_HINTS = {
    'screenshot': ArtifactSourceKind.SCREENSHOTS,
    'screenshots': ArtifactSourceKind.SCREENSHOTS,
    'app_screenshot': ArtifactSourceKind.SCREENSHOTS,
    'scheduled_screenshot': ArtifactSourceKind.SCREENSHOTS,
    'webcam': ArtifactSourceKind.WEBCAM,
    'camera': ArtifactSourceKind.WEBCAM,
    'clipboard': ArtifactSourceKind.CLIPBOARD,
    'clipboard_image': ArtifactSourceKind.CLIPBOARD,
    'clipboard_file': ArtifactSourceKind.CLIPBOARD,
    'script': ArtifactSourceKind.SCRIPT_FILE,
    'script_file': ArtifactSourceKind.SCRIPT_FILE,
    'job_file': ArtifactSourceKind.JOB_FILE,
    'job_output': ArtifactSourceKind.JOB_FILE,  # File uploads, not execution snapshots
    'command_output': ArtifactSourceKind.COMMAND_OUTPUT,
    'terminal_logs': ArtifactSourceKind.TERMINAL_LOGS,
    'terminal_output': ArtifactSourceKind.TERMINAL_LOGS,
    'pty_output': ArtifactSourceKind.TERMINAL_LOGS,
    'download': ArtifactSourceKind.DOWNLOADS,
    'downloads': ArtifactSourceKind.DOWNLOADS,
    'browser_download': ArtifactSourceKind.DOWNLOADS,
    'bundle': ArtifactSourceKind.DOWNLOADS,
    'recording': ArtifactSourceKind.INBOX,
    'manual': ArtifactSourceKind.INBOX,
    'other': ArtifactSourceKind.INBOX,
    'default': ArtifactSourceKind.INBOX,
    'inbox': ArtifactSourceKind.INBOX,
}
TERMINAL_SNAPSHOT_SOURCES = frozenset({'pty_toolbar_action', 'terminal_toolbar_action'})


def parse_artifact_type(value):
    return ArtifactType(value)


def scope_for_type(value):
    artifact_type = parse_artifact_type(value)
    return {
        ArtifactType.FILES: ArtifactScope.SAVED,
        ArtifactType.COMMAND_OUTPUT: ArtifactScope.SAVED,
        ArtifactType.SHARED_FILES: ArtifactScope.SHARED,
        ArtifactType.PREVIEWS: ArtifactScope.PREVIEW,
    }[artifact_type]


def saved_folder_id(source_kind):
    return SAVED_FOLDER_IDS[ArtifactSourceKind(source_kind)]


def saved_kind_for_folder(folder_id):
    return SAVED_SOURCE_BY_FOLDER_ID[folder_id]


def classify_artifact(artifact_type, producer_hint='', extra=None):
    artifact_type = parse_artifact_type(artifact_type)
    scope = scope_for_type(artifact_type)
    if scope == ArtifactScope.SHARED:
        return scope.value, ArtifactSourceKind.SHARED_UPLOAD.value, None
    if scope == ArtifactScope.PREVIEW:
        return scope.value, ArtifactSourceKind.PREVIEW_CACHE.value, None
    origin = str((extra or {}).get('source') or '').strip()
    if artifact_type == ArtifactType.COMMAND_OUTPUT:
        source = (ArtifactSourceKind.TERMINAL_LOGS if origin in TERMINAL_SNAPSHOT_SOURCES
                  else ArtifactSourceKind.COMMAND_OUTPUT)
    else:
        hint = str(producer_hint or '').strip().lower()
        if hint not in PRODUCER_HINTS and hint:
            raise ValueError(f'Unknown artifact producer category: {producer_hint}')
        source = PRODUCER_HINTS[hint] if hint else ArtifactSourceKind.INBOX
    return scope.value, source.value, SAVED_FOLDER_IDS[source]
