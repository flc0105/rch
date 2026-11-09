"""Explicit, Client-enforced destination conflict decisions for Remote Files."""

import hashlib
import os
import shutil
import tempfile
from datetime import datetime

POLICIES = frozenset({'stop', 'replace', 'merge', 'keep_both'})
UPLOAD_FILE_POLICIES = frozenset({'stop', 'replace', 'keep_both'})


def path_kind(path):
    if not os.path.lexists(path):
        return ''
    if os.path.islink(path):
        return 'link'
    return 'directory' if os.path.isdir(path) else 'file'


def allowed_actions(source_kind, target_kind):
    if not target_kind:
        return []
    if source_kind == 'directory' and target_kind == 'directory':
        return ['stop', 'merge', 'replace', 'keep_both']
    if source_kind == 'file' and target_kind == 'file':
        return ['stop', 'replace', 'keep_both']
    return ['stop', 'keep_both']


def describe_conflict(source, target, index=None):
    target_kind = path_kind(target)
    if not target_kind:
        return None
    source_kind = path_kind(source)
    result = {
        'source': source, 'target': target, 'source_kind': source_kind,
        'target_kind': target_kind, 'allowed_actions': allowed_actions(source_kind, target_kind),
    }
    if index is not None:
        result['index'] = index
    return result


def unique_destination(target):
    """Reserve no name: caller must use exclusive create/rename or recheck at commit."""
    directory, filename = os.path.split(target)
    stem, ext = os.path.splitext(filename)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    for attempt in range(128):
        digest = hashlib.sha256(os.urandom(16) + target.encode('utf-8', 'surrogatepass')).hexdigest()[:8]
        candidate = os.path.join(directory, f'{stem}_{stamp}_{digest}{ext}')
        if not os.path.lexists(candidate):
            return candidate
    raise FileExistsError('Unable to create a unique destination')


def _stage_copy(source, parent):
    temporary = tempfile.mkdtemp(prefix='.rch-conflict-', dir=parent)
    staged = os.path.join(temporary, 'incoming')
    try:
        if os.path.isdir(source) and not os.path.islink(source):
            shutil.copytree(source, staged, symlinks=True)
        elif os.path.islink(source):
            os.symlink(os.readlink(source), staged)
        else:
            shutil.copy2(source, staged)
        return temporary, staged
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _merge_directories(source, destination):
    # Preflight prevents type collisions before any leaf is changed.
    for root, directories, files in os.walk(source, followlinks=False):
        relative = os.path.relpath(root, source)
        target_dir = destination if relative == '.' else os.path.join(destination, relative)
        if path_kind(target_dir) not in ('', 'directory'):
            raise FileExistsError(f'Incompatible target: {target_dir}')
        for name in directories + files:
            src = os.path.join(root, name)
            dst = os.path.join(target_dir, name)
            kind = path_kind(src)
            existing = path_kind(dst)
            if existing and (kind != existing or kind == 'link'):
                raise FileExistsError(f'Incompatible target: {dst}')
    for root, directories, files in os.walk(source, followlinks=False):
        relative = os.path.relpath(root, source)
        target_dir = destination if relative == '.' else os.path.join(destination, relative)
        os.makedirs(target_dir, exist_ok=True)
        for name in directories:
            src, dst = os.path.join(root, name), os.path.join(target_dir, name)
            if os.path.islink(src):
                # Symlink entries are never followed or implicitly overwritten.
                if os.path.lexists(dst):
                    raise FileExistsError(f'Incompatible target: {dst}')
                os.symlink(os.readlink(src), dst)
            else:
                os.makedirs(dst, exist_ok=True)
        for name in files:
            src, dst = os.path.join(root, name), os.path.join(target_dir, name)
            if os.path.islink(src):
                if os.path.lexists(dst):
                    raise FileExistsError(f'Incompatible target: {dst}')
                os.symlink(os.readlink(src), dst)
                continue
            with tempfile.NamedTemporaryFile(prefix='.rch-file-', dir=target_dir, delete=False) as out:
                staged = out.name
            try:
                shutil.copy2(src, staged)
                os.replace(staged, dst)
            finally:
                if os.path.lexists(staged):
                    os.unlink(staged)


def apply_path(source, target, operation, policy='stop'):
    """Apply copy/move (or move from a private extraction stage) under one policy."""
    if policy not in POLICIES:
        raise ValueError(f'Unsupported conflict policy: {policy}')
    source = os.path.abspath(source)
    target = os.path.abspath(target)
    if source == target:
        if policy == 'keep_both':
            target = unique_destination(target)
        else:
            raise ValueError('Source and destination are the same')
    if os.path.isdir(source) and not os.path.islink(source):
        try:
            if os.path.commonpath([source, target]) == source:
                raise ValueError('Cannot copy or move a directory into itself')
        except ValueError as exc:
            if str(exc) == 'Cannot copy or move a directory into itself':
                raise
    source_kind = path_kind(source)
    if not source_kind:
        raise FileNotFoundError(source)
    target_kind = path_kind(target)
    if target_kind:
        if policy not in allowed_actions(source_kind, target_kind):
            raise FileExistsError(f'Target already exists ({source_kind} vs {target_kind}): {target}')
        if policy == 'keep_both':
            target = unique_destination(target)
            target_kind = ''
        elif policy == 'stop':
            raise FileExistsError(f'Target already exists: {target}')
    if target_kind and policy == 'merge':
        if source_kind != 'directory':
            raise ValueError('Merge requires two directories')
        _merge_directories(source, target)
        if operation == 'move':
            shutil.rmtree(source)
        return target
    if target_kind and policy == 'replace':
        parent = os.path.dirname(target)
        temporary, staged = _stage_copy(source, parent)
        backup = os.path.join(temporary, 'old')
        try:
            os.replace(target, backup)
            try:
                os.replace(staged, target)
            except BaseException:
                os.replace(backup, target)
                raise
            if operation == 'move':
                if source_kind == 'directory':
                    shutil.rmtree(source)
                else:
                    os.unlink(source)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        return target
    if operation == 'move':
        # Move into an absent path; retry conflicts are rejected by the destination check.
        shutil.move(source, target)
    elif operation == 'copy':
        if source_kind == 'directory':
            shutil.copytree(source, target, symlinks=True)
        elif source_kind == 'link':
            os.symlink(os.readlink(source), target)
        else:
            with open(source, 'rb') as stream, open(target, 'xb') as out:
                shutil.copyfileobj(stream, out, length=1024 * 1024)
            shutil.copystat(source, target)
    else:
        raise ValueError(f'Unsupported operation: {operation}')
    return target


def prepare_upload_file_commit(target, policy):
    """Validate an upload decision before transfer and return its publish callback."""
    if not isinstance(policy, str) or policy not in UPLOAD_FILE_POLICIES:
        raise ValueError('Invalid upload conflict policy')
    return lambda staged: commit_download_file(staged, target, policy)


def commit_download_file(staged, target, policy):
    """Publish a fully downloaded file only after validating its final destination."""
    if not isinstance(policy, str) or policy not in UPLOAD_FILE_POLICIES:
        raise ValueError('Invalid upload conflict policy')
    kind = path_kind(target)
    if kind and policy not in allowed_actions('file', kind):
        raise FileExistsError(f'Upload target already exists: {target}')
    if kind and policy == 'replace':
        os.replace(staged, target)
        return target
    if kind and policy == 'keep_both':
        for _ in range(16):
            unique = unique_destination(target)
            try:
                os.link(staged, unique)
            except FileExistsError:
                continue
            os.unlink(staged)
            return unique
        raise FileExistsError('Unable to allocate a unique upload name')
    os.link(staged, target)  # Atomic no-overwrite on the destination filesystem.
    os.unlink(staged)
    return target
