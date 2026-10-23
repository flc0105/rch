import os
import shutil
import tempfile
import threading


CLIENT_TEMP_ROOT_NAME = 'rch_client_temp'
_LOCK = threading.RLock()
_ACTIVE_PATHS = set()


def get_client_temp_root(create: bool = True) -> str:
    root = os.path.abspath(os.path.join(tempfile.gettempdir(), CLIENT_TEMP_ROOT_NAME))
    if create:
        os.makedirs(root, exist_ok=True)
    return root


def get_temp_category_dir(category: str, create: bool = True, *, private: bool = False) -> str:
    normalized = _normalize_category(category)
    path = os.path.join(get_client_temp_root(create=create), normalized)
    if create:
        os.makedirs(path, mode=0o700 if private else 0o777, exist_ok=True)
        if private and os.name != 'nt':
            # Staged clipboard contents and watchdog diagnostics may be sensitive.
            os.chmod(path, 0o700)
    return os.path.abspath(path)


def make_client_temp_dir(category: str, prefix: str = '') -> str:
    path = tempfile.mkdtemp(
        prefix=str(prefix or ''),
        dir=get_temp_category_dir(category, create=True),
    )
    register_temp_path(path)
    return os.path.abspath(path)


def make_client_temp_file(category: str, prefix: str = '', suffix: str = '') -> tuple[int, str]:
    fd, path = tempfile.mkstemp(
        prefix=str(prefix or ''),
        suffix=str(suffix or ''),
        dir=get_temp_category_dir(category, create=True),
    )
    path = os.path.abspath(path)
    register_temp_path(path)
    return fd, path


def register_temp_path(path: str):
    normalized = _normalize_path(path)
    if not normalized:
        return
    with _LOCK:
        _ACTIVE_PATHS.add(normalized)


def release_temp_path(path: str):
    normalized = _normalize_path(path)
    if not normalized:
        return
    with _LOCK:
        _ACTIVE_PATHS.discard(normalized)


def cleanup_temp_path(path: str):
    normalized = _normalize_path(path)
    if not normalized:
        return
    try:
        if os.path.isdir(normalized) and not os.path.islink(normalized):
            shutil.rmtree(normalized, ignore_errors=True)
        elif os.path.exists(normalized) or os.path.islink(normalized):
            try:
                os.remove(normalized)
            except FileNotFoundError:
                pass
    finally:
        release_temp_path(normalized)
        _prune_empty_managed_parents(normalized)


def path_contains_active_temp(path: str) -> bool:
    candidate = _normalize_path(path)
    if not candidate:
        return False

    with _LOCK:
        active_paths = tuple(_ACTIVE_PATHS)

    for active in active_paths:
        if active == candidate:
            return True
        try:
            if os.path.commonpath([active, candidate]) == candidate:
                return True
        except Exception:
            continue
    return False


def _normalize_category(category: str) -> str:
    normalized = str(category or '').strip().lower()
    if not normalized:
        raise ValueError('temp category is required')
    if not all(ch.isalnum() or ch in {'-', '_'} for ch in normalized):
        raise ValueError(f'invalid temp category: {category}')
    return normalized


def _normalize_path(path: str) -> str:
    text = str(path or '').strip()
    return os.path.abspath(text) if text else ''


def _prune_empty_managed_parents(path: str):
    root = get_client_temp_root(create=False)
    normalized_path = os.path.abspath(path)
    try:
        if os.path.commonpath([normalized_path, root]) != root:
            return
    except Exception:
        return

    current = os.path.dirname(normalized_path)
    while current and current != root:
        try:
            if not os.path.isdir(current) or os.listdir(current):
                break
            os.rmdir(current)
        except Exception:
            break
        current = os.path.dirname(current)

    try:
        if os.path.isdir(root) and not os.listdir(root):
            os.rmdir(root)
    except Exception:
        pass
