"""从 RCH 项目根目录构建前端，并发布到 backend/static。"""

import filecmp
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(".").resolve()
    frontend = root / "frontend"
    backend = root / "backend"
    dist = frontend / "dist"
    static = backend / "static"

    if not (frontend / "package.json").is_file() or not backend.is_dir():
        raise RuntimeError("请在 RCH 项目根目录执行（需要 frontend/package.json 和 backend/）。")
    if static.is_symlink():
        raise RuntimeError(f"拒绝清理符号链接目录：{static}")

    print("[1/4] 构建前端：npm run build", flush=True)
    subprocess.run(["npm", "run", "build"], cwd=frontend, check=True)

    if not dist.is_dir() or dist.is_symlink() or not (dist / "index.html").is_file():
        raise RuntimeError(f"构建产物异常，缺少 frontend/dist/index.html：{dist}")
    if any(path.is_symlink() for path in dist.rglob("*")):
        raise RuntimeError("dist 内包含符号链接，已停止发布。")
    source_files = {path.relative_to(dist) for path in dist.rglob("*") if path.is_file()}
    if not source_files:
        raise RuntimeError("dist 为空，已停止发布。")

    print("[2/4] 清理 backend/static 的旧内容", flush=True)
    static.mkdir(exist_ok=True)
    for item in static.iterdir():
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        else:
            item.unlink()

    print("[3/4] 复制 dist 目录内的全部内容到 backend/static", flush=True)
    for item in dist.iterdir():
        target = static / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)

    print("[4/4] 校验发布结果", flush=True)
    target_files = {path.relative_to(static) for path in static.rglob("*") if path.is_file()}
    if source_files != target_files:
        raise RuntimeError("复制校验失败：目标文件列表与 dist 不一致。")
    for relative in source_files:
        if not filecmp.cmp(dist / relative, static / relative, shallow=False):
            raise RuntimeError(f"复制校验失败：{relative}")

    print(f"[OK] 前端发布完成，共 {len(source_files)} 个文件：{static}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[ERROR] 发布失败：{exc}", file=sys.stderr)
        sys.exit(1)
