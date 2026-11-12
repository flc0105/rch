"""Canonical Artifact types and Saved category / virtual-folder contract."""
from enum import Enum


class ArtifactType(str, Enum):
    SAVED = 'saved'
    SHARED = 'shared'
    PREVIEW = 'preview'


class ArtifactCategory(str, Enum):
    SCREENSHOTS = 'screenshots'
    WEBCAM = 'webcam'
    DOWNLOADS = 'downloads'
    CLIPBOARD = 'clipboard'
    SCRIPT_FILES = 'script_files'
    JOB_FILES = 'job_files'
    COMMAND_OUTPUT = 'command_output'
    TERMINAL_LOGS = 'terminal_logs'
    INBOX = 'inbox'


# The only Saved category -> folder mapping. No old names or aliases.
SAVED_CATEGORY_FOLDERS = {
    ArtifactCategory.SCREENSHOTS: 'Screenshots',
    ArtifactCategory.WEBCAM: 'Webcam',
    ArtifactCategory.DOWNLOADS: 'Downloads',
    ArtifactCategory.CLIPBOARD: 'Clipboard',
    ArtifactCategory.SCRIPT_FILES: 'Script Files',
    ArtifactCategory.JOB_FILES: 'Job Files',
    ArtifactCategory.COMMAND_OUTPUT: 'Command Output',
    ArtifactCategory.TERMINAL_LOGS: 'Terminal Logs',
    ArtifactCategory.INBOX: 'Inbox',
}
SAVED_FOLDER_IDS = {category: f'{ArtifactType.SAVED.value}:{category.value}' for category in SAVED_CATEGORY_FOLDERS}
SAVED_CATEGORY_BY_FOLDER_ID = {folder_id: category for category, folder_id in SAVED_FOLDER_IDS.items()}


def normalize_saved_category(value):
    """Only the nine canonical categories are classified; all other input goes to Inbox."""
    if isinstance(value, ArtifactCategory):
        return value
    normalized = str(value or '').strip().casefold()
    try:
        return ArtifactCategory(normalized)
    except ValueError:
        return ArtifactCategory.INBOX


def parse_artifact_type(value):
    return ArtifactType(value)


def saved_folder_id(category):
    return SAVED_FOLDER_IDS[ArtifactCategory(category)]


def saved_category_for_folder(folder_id):
    return SAVED_CATEGORY_BY_FOLDER_ID[folder_id]


def classify_artifact(artifact_type, category=''):
    normalized_type = parse_artifact_type(artifact_type)
    if normalized_type != ArtifactType.SAVED:
        return normalized_type.value, None, None
    normalized = normalize_saved_category(category)
    return normalized_type.value, normalized.value, SAVED_FOLDER_IDS[normalized]
