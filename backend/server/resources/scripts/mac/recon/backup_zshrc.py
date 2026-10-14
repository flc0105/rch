SCRIPT_METADATA = {
    "display_name": "Backup zshrc to Artifacts",
    "description": "将 ~/.zshrc 备份到 artifacts，文件名带时间戳",
    "params": [],
    "api_grants": [
        "artifacts:save",
    ]
}

import os
import shutil
import tempfile
import time

from client.runtime.sdk import artifact


def main():
    print('=== Backup ~/.zshrc to Artifacts ===')

    src = os.path.expanduser('~/.zshrc')
    if not os.path.isfile(src):
        raise FileNotFoundError(f'source not found: {src}')
    print('source =', src, f'({os.path.getsize(src)} bytes)')

    stamp = time.strftime('%Y%m%d-%H%M%S')
    backup_name = f'zshrc-backup-{stamp}'

    tmp_dir = tempfile.mkdtemp(prefix='zshrc_backup_')
    tmp_path = os.path.join(tmp_dir, backup_name)
    shutil.copy2(src, tmp_path)
    print('staged =', tmp_path)

    saved = artifact.save(
        tmp_path,
        type='shared_files',
        category='zsh_config',
        extra={'kind': 'zshrc_backup', 'stamp': stamp},
    )
    print('saved =', saved)


if __name__ == '__main__':
    main()