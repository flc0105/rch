import os
import zipfile
from pathlib import Path
from datetime import datetime


# 当前脚本所在目录
BASE_DIR = Path(__file__).resolve().parent

# 需要压缩的目录
TARGET_DIRS = [
    "backend",
    "frontend",
    "desktop_notifier",
    "tools"
]

# 需要忽略的路径，相对于 BASE_DIR
IGNORE_PATHS = {
    "frontend/dist",
    "frontend/node_modules",
    "frontend/.vite",
    "frontend/.vscode",
    "backend/runtime",
    #"backend/static", # 生产环境解除
    "backend/venv",
    "backend/.pytest_cache",
    #"backend/server/resources/jobs",
    #"backend/server/resources/scripts",
    #"backend/server/resources/aliases.json",
    "backend/server/resources/external_tools/packages",
    "desktop_notifier/.venv",
    "desktop_notifier/config.json",
    "desktop_notifier/state.json",
    "desktop_notifier/nohup.out",
    "backend/docs/.silverbullet.auth.json"
}

# 统一转换为 Path
IGNORE_PATHS = {Path(p) for p in IGNORE_PATHS}


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / 1024 ** 2:.2f} MB"
    else:
        return f"{size_bytes / 1024 ** 3:.2f} GB"


def should_ignore(path: Path) -> bool:
    """
    判断文件或目录是否需要忽略
    path 是绝对路径
    """
    rel_path = path.relative_to(BASE_DIR)

    # 忽略所有 .pyc 文件
    if path.is_file() and path.suffix == ".pyc":
        return True

    # 忽略 __pycache__ 或 pycache 目录
    if any(part in {"__pycache__", "pycache"} for part in rel_path.parts):
        return True

    # 忽略任何层级的虚拟环境、依赖目录及开发缓存
    if any(part in {
        ".venv", "venv", "node_modules", ".git", ".idea", ".vscode",
        ".vite", ".pytest_cache", ".mypy_cache", ".ruff_cache"
    } for part in rel_path.parts):
        return True

    # 忽略系统元数据、备份和临时文件
    if path.is_file() and (
        path.name in {".DS_Store", "Thumbs.db", "desktop.ini"}
        or path.suffix in {".pyo", ".bak", ".swp", ".swo"}
        or path.name.endswith("~")
    ):
        return True

    # 忽略本地环境配置，但保留可提交的示例配置
    if path.is_file() and (
        path.name == ".env"
        or (
            path.name.startswith(".env.")
            and path.name not in {".env.example", ".env.sample", ".env.template"}
        )
    ):
        return True

    # 忽略指定路径及其子路径
    for ignore_path in IGNORE_PATHS:
        if rel_path == ignore_path or ignore_path in rel_path.parents:
            return True

    return False


def zip_project():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"rch_project_{timestamp}.zip"
    zip_path = BASE_DIR / zip_name

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for target_dir in TARGET_DIRS:
            root_dir = BASE_DIR / target_dir

            if not root_dir.exists():
                print(f"警告：目录不存在，已跳过：{root_dir}")
                continue

            for current_root, dirs, files in os.walk(root_dir):
                current_root_path = Path(current_root)

                # 过滤目录，避免进入被忽略的目录
                dirs[:] = [
                    d for d in dirs
                    if not should_ignore(current_root_path / d)
                ]

                # 添加文件
                for file in files:
                    file_path = current_root_path / file

                    if should_ignore(file_path):
                        continue

                    arcname = file_path.relative_to(BASE_DIR)
                    zipf.write(file_path, arcname)

    zip_size = zip_path.stat().st_size

    print("压缩完成")
    print(f"ZIP 文件路径：{zip_path}")
    print(f"ZIP 文件大小：{format_size(zip_size)}")


if __name__ == "__main__":
    zip_project()
