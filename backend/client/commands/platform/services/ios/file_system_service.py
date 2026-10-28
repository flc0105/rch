import hashlib
import os
import re
import urllib.request


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

    def acmd_find(self, args_dict):
        try:
            path = args_dict.get('path', '.')
            keyword = args_dict['keyword']

            target = self.expand_path(path, default='.')
            word = (keyword or '').strip()

            if not os.path.exists(target):
                return 0, f'Path not found: {target}'
            if not os.path.isdir(target):
                return 0, f'Not a directory: {target}'
            if not word:
                return 0, 'Option "--keyword" cannot be empty'

            results = []
            for root, dirs, files in os.walk(target):
                for name in dirs + files:
                    if word.lower() in name.lower():
                        results.append(os.path.join(root, name))

            if not results:
                return 1, ''

            return 1, '\n'.join(results)
        except Exception as e:
            return 0, f'find failed: {e}'

    def acmd_tree(self, args_dict):
        try:
            path = args_dict.get('path', '.')
            max_depth = args_dict.get('max_depth', 3)

            target = self.expand_path(path, default='.')
            depth_limit = int(max_depth)

            if not os.path.exists(target):
                return 0, f'Path not found: {target}'
            if not os.path.isdir(target):
                return 0, f'Not a directory: {target}'
            if depth_limit < 0:
                return 0, 'Option "--max_depth" must be >= 0'

            lines = [os.path.basename(target.rstrip('/')) or target]

            def walk(current, prefix='', depth=0):
                if depth >= depth_limit:
                    return

                items = sorted(
                    os.listdir(current),
                    key=lambda name: (
                        0 if os.path.isdir(os.path.join(current, name)) else 1,
                        name.lower()
                    )
                )

                for i, name in enumerate(items):
                    full = os.path.join(current, name)
                    is_last = i == len(items) - 1
                    branch = '└── ' if is_last else '├── '
                    suffix = '/' if os.path.isdir(full) else ''
                    lines.append(prefix + branch + name + suffix)

                    if os.path.isdir(full):
                        walk(full, prefix + ('    ' if is_last else '│   '), depth + 1)

            walk(target)
            return 1, '\n'.join(lines)
        except Exception as e:
            return 0, f'tree failed: {e}'

    def acmd_head(self, args_dict):
        try:
            path = self.expand_path(args_dict.get('path'), default='')
            lines_count = int(args_dict.get('lines', 10))

            if not os.path.exists(path):
                return 0, f'Path not found: {path}'
            if not os.path.isfile(path):
                return 0, f'Not a file: {path}'
            if lines_count < 0:
                return 0, 'Option "--lines" must be >= 0'

            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            return 1, ''.join(lines[:lines_count]).rstrip('\n')
        except Exception as e:
            return 0, f'head failed: {e}'

    def acmd_tail(self, args_dict):
        try:
            path = self.expand_path(args_dict.get('path'), default='')
            lines_count = int(args_dict.get('lines', 10))

            if not os.path.exists(path):
                return 0, f'Path not found: {path}'
            if not os.path.isfile(path):
                return 0, f'Not a file: {path}'
            if lines_count < 0:
                return 0, 'Option "--lines" must be >= 0'

            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            return 1, ''.join(lines[-lines_count:] if lines_count else []).rstrip('\n')
        except Exception as e:
            return 0, f'tail failed: {e}'

    def acmd_wget(self, args_dict):
        try:
            url = str(args_dict.get('url') or '').strip()
            out = str(args_dict.get('output') or '').strip()

            if not url:
                return 0, 'Missing required option: --url'

            if out:
                out_path = os.path.expanduser(out)
            else:
                name = url.rstrip('/').split('/')[-1] or 'download.bin'
                out_path = os.path.join(os.getcwd(), name)  # 默认下载到当前目录

            out_dir = os.path.dirname(out_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)

            with urllib.request.urlopen(url) as resp:
                with open(out_path, 'wb') as f:
                    while True:
                        chunk = resp.read(1024 * 256)
                        if not chunk:
                            break
                        f.write(chunk)

            return 1, out_path
        except Exception as e:
            return 0, f'wget failed: {e}'