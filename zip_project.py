import os
import re
import zipfile
from pathlib import Path
from datetime import datetime


# 当前脚本所在目录
BASE_DIR = Path(__file__).resolve().parent

# 源码目录与需要保留的根目录文件
TARGET_DIRS = ("backend", "frontend", "desktop_notifier", "tools")
TARGET_FILES = ("README.md", "zip_project.py")

# 各层级通用的依赖、版本管理、编辑器及缓存目录
IGNORE_DIR_NAMES = {
    "__pycache__", "pycache", ".venv", "venv", "node_modules", ".git",
    ".idea", ".vscode", ".vite", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".nox", ".cache",
}
IGNORE_FILE_NAMES = {
    ".DS_Store", "Thumbs.db", "desktop.ini", "nohup.out", ".silverbullet.auth.json",
}
IGNORE_SUFFIXES = {".pyc", ".pyo", ".bak", ".swp", ".swo"}
ENV_EXAMPLES = {".env.example", ".env.sample", ".env.template"}
ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".7z", ".rar")
LOG_PATTERN = re.compile(r"\.log(?:\.\d+)?(?:\.gz)?$", re.IGNORECASE)

# 仅在明确的项目路径下排除构建产物和本地运行数据。
# 不按 runtime、static 等通用名称过滤，以免误删源码目录。
IGNORE_PATHS = {Path(p) for p in (
    "frontend/dist",
    "backend/runtime",
    "backend/static",  # 如需打包生产静态产物，可解除此项
    "backend/server/resources/external_tools/packages",
    "desktop_notifier/config.json",
    "desktop_notifier/state.json",
)}

# 资源目录及测试夹具中的压缩包可以是项目输入；其他目录的归档按备份/产物处理。
ARCHIVE_INPUT_ROOTS = {Path(p) for p in (
    "backend/server/resources", "backend/tests", "frontend/tests", "desktop_notifier/tests",
)}


def format_size(size_bytes: int) -> str:
    """格式化文件大小。"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / 1024 ** 2:.2f} MB"
    else:
        return f"{size_bytes / 1024 ** 3:.2f} GB"


def is_within(relative: Path, roots: set[Path]) -> bool:
    return any(relative == root or root in relative.parents for root in roots)


def should_ignore(path: Path) -> bool:
    """判断 BASE_DIR 下的绝对路径是否需要忽略。"""
    rel_path = path.relative_to(BASE_DIR)
    # 不跟随符号链接，避免将项目边界之外的内容写入快照。
    if path.is_symlink() or is_within(rel_path, IGNORE_PATHS):
        return True
    if any(part in IGNORE_DIR_NAMES for part in rel_path.parts[:-1]) or (
        path.is_dir() and path.name in IGNORE_DIR_NAMES
    ):
        return True
    if not path.is_file():
        return False

    name = path.name
    # 系统元数据、缓存、备份、编辑器临时文件及运行日志。
    if (name in IGNORE_FILE_NAMES or path.suffix.lower() in IGNORE_SUFFIXES
            or name.endswith("~") or LOG_PATTERN.search(name)):
        return True
    # 本地环境配置；示例配置仍属于源码快照。
    if (name == ".env" or name.startswith(".env.")) and name not in ENV_EXAMPLES:
        return True
    if name.lower().endswith(ARCHIVE_SUFFIXES) and not is_within(rel_path, ARCHIVE_INPUT_ROOTS):
        return True
    return False


def iter_project_files():
    for name in TARGET_FILES:
        path = BASE_DIR / name
        if path.is_file() and not should_ignore(path):
            yield path
        else:
            print(f"警告：根目录文件不存在或被忽略：{path}")

    for target_dir in TARGET_DIRS:
        root_dir = BASE_DIR / target_dir
        if not root_dir.is_dir() or should_ignore(root_dir):
            print(f"警告：目录不存在或被忽略：{root_dir}")
            continue
        for current_root, dirs, files in os.walk(root_dir):
            current_root_path = Path(current_root)
            # 过滤目录，避免进入被忽略的目录；固定顺序便于比较快照。
            dirs[:] = sorted(d for d in dirs if not should_ignore(current_root_path / d))
            for name in sorted(files):
                file_path = current_root_path / name
                if file_path.is_file() and not should_ignore(file_path):
                    yield file_path


def zip_project():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    zip_path = BASE_DIR / f"rch_project_{timestamp}.zip"
    # 某些源码归档保留早于 ZIP 格式支持范围的文件时间。
    archive = zipfile.ZipFile(zip_path, "x", zipfile.ZIP_DEFLATED, strict_timestamps=False)
    try:
        with archive as zipf:
            for file_path in iter_project_files():
                zipf.write(file_path, file_path.relative_to(BASE_DIR).as_posix())
    except BaseException:
        zip_path.unlink(missing_ok=True)
        raise

    zip_size = zip_path.stat().st_size
    print("压缩完成")
    print(f"ZIP 文件路径：{zip_path}")
    print(f"ZIP 文件大小：{format_size(zip_size)}")
    return zip_path


if __name__ == "__main__":
    zip_project()
