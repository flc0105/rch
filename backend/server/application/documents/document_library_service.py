"""Server-local Markdown directories. No database, remote Client, or path-based file API."""

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path, PurePosixPath

from core.utils.text_encoding import decode_text_bytes, encode_for_existing_file


class DocumentLibraryService:
    def __init__(self, roots: dict[str, str], max_bytes: int):
        if not isinstance(roots, dict) or not roots:
            raise ValueError("Document roots must be a non-empty mapping")
        self.roots = {}
        for key, entry in roots.items():
            if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]*", key):
                raise ValueError("Invalid document root ID")
            if isinstance(entry, str):
                entry = {"path": entry, "label": key}
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ValueError("Invalid document root configuration")
            location = Path(os.path.expanduser(entry["path"]))
            if not location.is_absolute():
                raise ValueError("Document root paths must be absolute")
            self.roots[key] = {"path": location.resolve(), "label": str(entry.get("label") or key)}
        self.max_bytes = max_bytes

    def list_roots(self):
        return {"items": [
            {"id": key, "label": value["label"]}
            for key, value in self.roots.items()
        ]}

    def _path(self, root_id, relative_path='', *, kind=None):
        if root_id not in self.roots:
            raise ValueError("Unknown document root")
        root = self.roots[root_id]["path"]
        if not root.is_dir():
            raise FileNotFoundError("Document root is unavailable")
        if not isinstance(relative_path, str) or "\\" in relative_path or "\x00" in relative_path:
            raise ValueError("Invalid document path")
        if relative_path.startswith('/'):
            raise ValueError("Absolute document paths are not allowed")
        parts = [] if not relative_path else relative_path.split('/')
        if any(part in ('', '.', '..') or part.startswith('.') or part.strip() != part for part in parts):
            raise ValueError("Document path traversal is not allowed")
        path = root.joinpath(*parts)
        # Reject links in every component, even links that happen to point inside the root.
        probe = root
        for part in parts:
            probe = probe / part
            if probe.is_symlink():
                raise ValueError("Symbolic links are not supported in Documents")
        if not path.resolve(strict=False).is_relative_to(root):
            raise ValueError("Document path is outside the configured root")
        if kind == 'file' and (not parts or path.suffix.lower() != '.md'):
            raise ValueError("Only .md documents are allowed")
        return path

    def list_tree(self, root_id, path=''):
        directory = self._path(root_id, path)
        if not directory.is_dir():
            raise FileNotFoundError("Directory not found")
        items = []
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.startswith('.') or entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    node_type = 'directory'
                elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith('.md'):
                    node_type = 'file'
                else:
                    continue
                items.append({"name": entry.name, "path": f"{path}/{entry.name}".lstrip('/'), "type": node_type})
        items.sort(key=lambda item: (item['type'] != 'directory', item['name'].casefold()))
        return {"items": items}

    def read_document(self, root_id, path):
        file_path = self._path(root_id, path, kind='file')
        if not file_path.is_file():
            raise FileNotFoundError("Document not found")
        with file_path.open('rb') as stream:
            data = stream.read(self.max_bytes + 1)
        if len(data) > self.max_bytes:
            raise ValueError("Document exceeds the edit size limit")
        try:
            content, encoding = decode_text_bytes(data)
        except (UnicodeError, ValueError):
            return {"path": path, "content": data.decode('utf-8', errors='replace'),
                    "encoding": "unknown", "editable": False,
                    "sha256": hashlib.sha256(data).hexdigest()}
        return {"path": path, "content": content, "encoding": encoding,
                "editable": True, "sha256": hashlib.sha256(data).hexdigest()}

    def save_document(self, root_id, path, content, encoding, sha256):
        file_path = self._path(root_id, path, kind='file')
        if not isinstance(sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', sha256):
            raise ValueError("Document revision is required")
        if not isinstance(content, str):
            raise ValueError("Document content must be text")
        with file_path.open('rb') as stream:
            original = stream.read(self.max_bytes + 1)
        if len(original) > self.max_bytes:
            raise ValueError("Document exceeds the edit size limit")
        if hashlib.sha256(original).hexdigest() != sha256:
            raise ValueError("Document changed on disk; reload before saving")
        try:
            output = encode_for_existing_file(content, encoding, original)
        except (UnicodeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        if len(output) > self.max_bytes:
            raise ValueError("Document exceeds the edit size limit")
        # Encode before opening the destination; replace is atomic on the same filesystem.
        original_stat = file_path.stat()
        fd, temporary = tempfile.mkstemp(prefix='.rch-document-', dir=file_path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                # Keep source ownership when the Server runs as root; retain file mode.
                if hasattr(os, 'fchown'):
                    try:
                        os.fchown(stream.fileno(), original_stat.st_uid, original_stat.st_gid)
                    except PermissionError:
                        pass
                if hasattr(os, 'fchmod'):
                    os.fchmod(stream.fileno(), stat.S_IMODE(original_stat.st_mode))
                stream.write(output)
                stream.flush()
                os.fsync(stream.fileno())
            # Recheck for external changes immediately before replacement.
            with file_path.open('rb') as stream:
                current = stream.read(self.max_bytes + 1)
            if hashlib.sha256(current).hexdigest() != sha256:
                raise ValueError("Document changed on disk; reload before saving")
            self._path(root_id, path, kind='file')
            os.replace(temporary, file_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {"path": path, "sha256": hashlib.sha256(output).hexdigest(), "encoding": encoding}

    def create_directory(self, root_id, path):
        directory = self._path(root_id, path)
        if directory == self.roots[root_id]['path']:
            raise ValueError("Directory name is required")
        if not directory.parent.is_dir():
            raise FileNotFoundError("Parent directory not found")
        directory.mkdir()
        return {"path": path}

    def create_document(self, root_id, path):
        file_path = self._path(root_id, path, kind='file')
        if not file_path.parent.is_dir():
            raise FileNotFoundError("Parent directory not found")
        # Exclusive create: never truncate an existing note (or follow a symlink).
        with file_path.open('xb'):
            pass
        return self.read_document(root_id, path)
