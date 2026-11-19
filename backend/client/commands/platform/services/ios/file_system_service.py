import hashlib
import os
import re


class iOSFileSystemService:
    """
    iOS / Pythonista 文件系统能力。
    """

    def __init__(self, owner):
        self.owner = owner

    def expand_path(self, path, default='.'):
        return os.path.expanduser((path or default).strip())

    def list_directory(self, path):
        try:
            target = self.expand_path(path, default='.')
            if not os.path.exists(target):
                return 0, f'Path not found: {target}'
            if not os.path.isdir(target):
                return 0, f'Not a directory: {target}'

            entries = []
            for name in os.listdir(target):
                full = os.path.join(target, name)
                is_dir = os.path.isdir(full)
                is_link = os.path.islink(full)
                display_name = f'{name}/' if is_dir else (f'{name}@' if is_link else name)
                entries.append((0 if is_dir else 1, name.lower(), display_name))

            entries.sort(key=lambda x: (x[0], x[1]))
            return 1, '\n'.join(item[2] for item in entries)
        except Exception as e:
            return 0, f'ls failed: {e}'

    def touch(self, path):
        try:
            target = self.expand_path(path, default='')
            if not target:
                return 0, 'Usage: touch <path>'

            parent = os.path.dirname(target)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)

            with open(target, 'a', encoding='utf-8'):
                os.utime(target, None)

            return 1, f'File touched: {target}'
        except Exception as e:
            return 0, f'touch failed: {e}'

    def cat(self, path):
        try:
            target = self.expand_path(path, default='')
            if not target:
                return 0, 'Usage: cat <file>'

            if not os.path.exists(target):
                return 0, f'Path not found: {target}'
            if not os.path.isfile(target):
                return 0, f'Not a file: {target}'

            with open(target, 'r', encoding='utf-8', errors='replace') as f:
                return 1, f.read()
        except Exception as e:
            return 0, f'cat failed: {e}'

    def md5sum(self, path):
        try:
            target = self.expand_path(path, default='')
            if not target:
                return 0, 'Usage: md5sum <file>'
            if not os.path.exists(target):
                return 0, f'Path not found: {target}'
            if not os.path.isfile(target):
                return 0, f'Not a file: {target}'

            md5 = hashlib.md5()
            with open(target, 'rb') as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b''):
                    md5.update(chunk)

            return 1, f'{md5.hexdigest()}  {target}'
        except Exception as e:
            return 0, f'md5sum failed: {e}'

    def printenv(self, name):
        try:
            key = (name or '').strip()
            if key:
                return 1, str(os.environ.get(key, ''))

            lines = []
            for env_name in sorted(os.environ.keys()):
                lines.append(f'{env_name}={os.environ.get(env_name, "")}')
            return 1, '\n'.join(lines)
        except Exception as e:
            return 0, f'printenv failed: {e}'

    def echo(self, text):
        try:
            raw = str(text or '')

            def repl(match):
                name = match.group(1) or match.group(2) or ''
                return str(os.environ.get(name, ''))

            rendered = re.sub(r'\$([A-Za-z_][A-Za-z0-9_]*)|\$\{([^}]+)\}', repl, raw)
            return 1, rendered
        except Exception as e:
            return 0, f'echo failed: {e}'
