"""Names for automatically produced Artifact files."""

import re
import shlex
from datetime import datetime


ARTIFACT_TIMESTAMP_FORMAT = '%Y%m%d_%H%M%S'
# Only command namespaces/wrappers that are uninformative without their next word.
COMMAND_NAME_TWO_WORD_PREFIXES = frozenset({'shell', 'shell_stream', 'acmd'})


def clean_artifact_label(value: str, *, max_length: int = 48) -> str:
    """Keep a short, filesystem-friendly label without interpreting commands."""
    label = re.sub(r'[^a-z0-9]+', '_', str(value or '').strip().lower()).strip('_')
    return label[:max_length].strip('_')


def build_command_name(command: str, *, max_length: int = 32) -> str:
    """Use the first command word, plus a second for configured generic prefixes."""
    text = str(command or '').strip()
    if not text:
        return 'output'
    try:
        tokens = shlex.split(text, posix=False)
    except ValueError:
        tokens = text.split()
    names = []
    for token in tokens:
        word = token.strip('"\'`')
        if not word or not any(char.isalnum() for char in word):
            continue
        if word.startswith('-'):
            break
        # Shell arguments may contain paths; keep the executable/operation leaf only.
        word = word.replace('\\', '/').rsplit('/', 1)[-1]
        label = clean_artifact_label(word, max_length=max_length)
        if label:
            names.append(label)
        if names and (len(names) == 2 or names[0] not in COMMAND_NAME_TWO_WORD_PREFIXES):
            break
    return clean_artifact_label('_'.join(names), max_length=max_length) or 'output'


def build_artifact_filename(prefix: str, extension: str, *, now=None, label: str = '') -> str:
    """Create prefix_YYYYMMDD_HHMMSS[_label].ext for an automatic Artifact."""
    normalized_prefix = clean_artifact_label(prefix)
    if not normalized_prefix:
        raise ValueError('Artifact filename prefix is required')
    ext = str(extension or '').strip().lower().lstrip('.')
    if not ext or not ext.isalnum():
        raise ValueError('Artifact file extension is invalid')
    timestamp = (now or datetime.now()).strftime(ARTIFACT_TIMESTAMP_FORMAT)
    clean_label = clean_artifact_label(label)
    suffix = f'_{clean_label}' if clean_label else ''
    return f'{normalized_prefix}_{timestamp}{suffix}.{ext}'
