SCRIPT_METADATA = {
    'name': "common/music/validate_mora_flac",
    'display_name': 'mora FLAC Check',
    'description': 'Check padding length, tag order, and metadata block layout in mora FLAC files.',
    'platforms': ['common'],
    'category': 'Music',
    'params': [
        {
            'name': 'directory',
            'label': 'Scan Folder',
            'type': 'remote_folder',
            'required': True,
            'description': 'Choose a folder on the selected device. Subfolders are included.',
        },
        {
            'name': 'errors_only',
            'label': 'Show Errors Only',
            'type': 'boolean',
            'default': False,
            'description': 'Show failed files and the scan summary only.',
        },
    ],
}

import os
from pathlib import Path

from client.runtime.sdk import context


MORA_MARKER_TAG = '45b1d925-1448-5784-b4da-b89901050a13'
MORA_MARKER_VALUE = '10006001'
MORA_LAST_TAGS = (
    '50dbf5a2-f864-5c17-be00-c36dfd3df7b4',
    'ff8ca75f-2d68-52eb-85d6-1580486025a4',
)
PADDING_BASES = (8244, 8258, 8288, 8302)
MORA_BLOCK_PREFIX = (0, 4, 6, 1)
BLOCK_NAMES = {0: 'STREAMINFO', 1: 'PADDING', 4: 'VORBIS COMMENT', 6: 'PICTURE'}


def has_mora_marker(tags):
    marker_values = tags.get(MORA_MARKER_TAG, ()) if tags is not None else ()
    return bool(marker_values) and marker_values[0] == MORA_MARKER_VALUE


def check_padding_length(flac):
    try:
        # Preserve the original rule: read length from the final metadata block.
        actual_length = flac.metadata_blocks[-1].length
    except (AttributeError, IndexError):
        return False, 'Could not read the length of the final metadata block.'

    if actual_length == 40:
        return True, '40 bytes (fixed length)'

    duration_increment = (flac.info.length // 10) * 18
    expected_lengths = tuple(base + duration_increment for base in PADDING_BASES)
    if actual_length in expected_lengths:
        return True, f'{actual_length} bytes (matches the duration-based rule)'

    expected = ', '.join(f'{length:.0f}' for length in (40, *expected_lengths))
    return False, f'Found {actual_length} bytes. Expected one of these lengths: {expected} bytes.'


def check_tag_endpoints(tags):
    # Mutagen's ordered tag pairs preserve the spelling stored in the file.
    tag_pairs = list(tags)
    first_tag = tag_pairs[0][0]
    last_tag = tag_pairs[-1][0]
    passed = first_tag == 'ARTIST' and last_tag in MORA_LAST_TAGS
    actual = f'{first_tag} → {last_tag}'
    if passed:
        return True, actual

    expected_last = ' or '.join(MORA_LAST_TAGS)
    return False, f'Found {actual}. Expected ARTIST first and {expected_last} last.'


def check_block_prefix(metadata_blocks):
    # The original rule checks the four leading blocks and allows additional ones.
    leading_codes = tuple(block.code for block in metadata_blocks[:len(MORA_BLOCK_PREFIX)])
    actual = ' → '.join(BLOCK_NAMES.get(code, str(code)) for code in leading_codes) or 'none'
    if leading_codes == MORA_BLOCK_PREFIX:
        return True, actual

    expected = ' → '.join(BLOCK_NAMES[code] for code in MORA_BLOCK_PREFIX)
    return False, f'Found {actual}. Expected {expected}.'


def report_mora_file(path, flac, errors_only):
    checks = (
        ('Padding length', check_padding_length(flac)),
        ('Tag order', check_tag_endpoints(flac.tags)),
        ('Metadata block order', check_block_prefix(flac.metadata_blocks)),
    )
    passed = all(result for _, (result, _) in checks)
    if passed:
        if not errors_only:
            context.progress(f'[PASS] {path}', level='success')
        return True

    lines = [f'[FAIL] {path}']
    for label, (result, detail) in checks:
        lines.append(f'  {label} | {"Pass" if result else "Fail"} | {detail}')
    context.progress('\n'.join(lines), level='error')
    return False


def main(params):
    try:
        from mutagen import MutagenError
        from mutagen.flac import FLAC
    except ImportError:
        context.progress('Could not load Mutagen. Install mutagen in the Python environment used by this Client.',
                         level='error')
        return

    directory = Path(params['directory']).expanduser()
    errors_only = params.get('errors_only', False)
    passed_count = failed_count = skipped_count = directory_error_count = 0

    def report_directory_error(exc):
        nonlocal directory_error_count
        directory_error_count += 1
        context.progress(f'{exc.filename or directory}  ·  Could not read folder\n  {exc.strerror or exc}',
                         level='error')

    for current_dir, subdirectories, filenames in os.walk(directory, onerror=report_directory_error):
        subdirectories.sort()
        for filename in sorted(filenames):
            if filename.startswith('._') or not filename.endswith('.flac'):
                continue

            file_path = Path(current_dir, filename)
            display_path = file_path.relative_to(directory)
            try:
                flac = FLAC(file_path)
            except (MutagenError, OSError) as exc:
                failed_count += 1
                context.progress(f'[FAIL] {display_path}\n  File read | Fail | {exc}', level='error')
                continue

            if not has_mora_marker(flac.tags):
                skipped_count += 1
                if not errors_only:
                    context.progress(
                        f'[SKIP] {display_path} (no mora marker found)',
                        level='warning',
                    )
            elif report_mora_file(display_path, flac, errors_only):
                passed_count += 1
            else:
                failed_count += 1

    context.progress(
        f'Scan complete | Passed: {passed_count} | Failed: {failed_count} | Skipped: {skipped_count}'
        f' | Folder read errors: {directory_error_count}',
        level='info',
    )


if __name__ == '__main__':
    main(kwargs)