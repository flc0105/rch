#!/usr/bin/env python3
# -*- coding: utf-8 -*-

SCRIPT_METADATA = {
    "name": "windows/system/recycle_bin",
    "display_name": "Recycle Bin Contents",
    "description": "List all items in Recycle Bin",
    "platforms": ["windows"],
    "category": "System",
    "params": []
}

"""将 Windows 回收站条目输出为 JSON 数组；仅使用 Python 标准库。

字段与 macOS 版本保持一致：name、type、original_path、trash_path、deleted_at、size。
支持 Windows Vista/7/8 的 $I v1 元数据，以及 Windows 10/11 的 $I v2 元数据。
"""
import ctypes
import datetime as dt
import json
import os
import stat
import sys
from pathlib import Path


FILETIME_EPOCH = dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc)
FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def current_user_sid():
    """通过 Windows 自带 whoami 获取当前进程用户的 SID。"""
    import csv
    import io
    import subprocess

    result = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for row in csv.reader(io.StringIO(result.stdout)):
        if len(row) >= 2:
            sid = row[-1].strip()
            if sid.startswith("S-"):
                return sid
    raise RuntimeError("无法从 whoami 的输出中获取当前用户 SID")


def volume_roots():
    """返回带盘符的固定磁盘、可移动磁盘和 RAM 磁盘根目录。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_logical_drives = kernel32.GetLogicalDrives
    get_logical_drives.argtypes = []
    get_logical_drives.restype = ctypes.c_uint32

    get_drive_type = kernel32.GetDriveTypeW
    get_drive_type.argtypes = [ctypes.c_wchar_p]
    get_drive_type.restype = ctypes.c_uint

    mask = get_logical_drives()
    # DRIVE_REMOVABLE=2, DRIVE_FIXED=3, DRIVE_RAMDISK=6
    accepted_types = {2, 3, 6}
    for index in range(26):
        if mask & (1 << index):
            root = f"{chr(ord('A') + index)}:\\"
            if get_drive_type(root) in accepted_types:
                yield Path(root)


def parse_i_metadata(i_path):
    """解析配对的 $I 文件，返回 (原始绝对路径或 None, 删除时间或 None)。"""
    try:
        data = i_path.read_bytes()
        if len(data) < 24:
            raise ValueError("$I 元数据长度不足")

        version = int.from_bytes(data[0:8], "little", signed=False)
        filetime = int.from_bytes(data[16:24], "little", signed=False)

        if version == 1:
            # v1: 24 字节头部 + 固定 520 字节 UTF-16LE 路径字段
            if len(data) < 544:
                raise ValueError("$I v1 元数据不完整")
            path_bytes = data[24:544]
        elif version == 2:
            # v2: 24 字节头部 + 4 字节字符数 + UTF-16LE 路径
            if len(data) < 28:
                raise ValueError("$I v2 元数据头部不完整")
            char_count = int.from_bytes(data[24:28], "little", signed=False)
            if char_count < 1:
                raise ValueError("$I v2 路径长度无效")
            end = 28 + char_count * 2
            if end > len(data):
                raise ValueError("$I v2 路径数据不完整")
            path_bytes = data[28:end]
        else:
            raise ValueError(f"不支持的 $I 元数据版本: {version}")

        original_path = path_bytes.decode("utf-16le").split("\x00", 1)[0]
        if not original_path:
            original_path = None

        deleted_at = None
        if filetime > 0:
            try:
                # FILETIME 为 UTC，自 1601-01-01 起以 100ns 为单位。
                utc_time = FILETIME_EPOCH + dt.timedelta(microseconds=filetime // 10)
                deleted_at = utc_time.astimezone().strftime("%Y-%m-%d %H:%M:%S")
            except (OverflowError, ValueError, OSError):
                deleted_at = None

        return original_path, deleted_at
    except (OSError, ValueError, UnicodeError) as exc:
        print(f"无法读取回收站元数据 {i_path}: {exc}", file=sys.stderr)
        return None, None


def is_reparse_point(st):
    """判断 Windows 符号链接、junction 等重解析点，避免递归跟随。"""
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def directory_file_bytes(path):
    """递归累计目录内普通文件的逻辑字节数，不跟随重解析点。读取不完整时返回 None。"""
    total = 0
    stack = [os.fspath(path)]
    try:
        while stack:
            current = stack.pop()
            with os.scandir(current) as entries:
                for entry in entries:
                    child_st = entry.stat(follow_symlinks=False)
                    if is_reparse_point(child_st):
                        # 与 macOS 版本不跟随符号链接的行为一致。
                        continue
                    if stat.S_ISDIR(child_st.st_mode):
                        stack.append(entry.path)
                    elif stat.S_ISREG(child_st.st_mode):
                        total += child_st.st_size
        return total
    except OSError as exc:
        print(f"无法完整计算目录大小 {path}: {exc}", file=sys.stderr)
        return None


def human_readable_size(size_bytes):
    """将字节数格式化为 B/KB/MB/GB/TB；无法计算时返回 None。"""
    if size_bytes is None:
        return None
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.2f} {unit}"
        size /= 1024


def scan_recycle_bin(recycle_dir, rows):
    """扫描当前用户在某个卷上的回收站，只输出实际内容文件 $R。"""
    try:
        with os.scandir(recycle_dir) as entries:
            for entry in entries:
                # 正常 Windows 回收站内容名以 $R 开头；配对元数据以 $I 开头。
                if not entry.name.startswith("$R"):
                    continue
                r_path = Path(entry.path)
                i_path = r_path.with_name("$I" + entry.name[2:])

                original_path, deleted_at = parse_i_metadata(i_path)
                try:
                    st = os.stat(r_path, follow_symlinks=False)
                except OSError as exc:
                    print(f"无法读取回收站条目 {r_path}: {exc}", file=sys.stderr)
                    continue

                # 不把符号链接或 junction 当作可递归目录。
                is_dir = stat.S_ISDIR(st.st_mode) and not is_reparse_point(st)
                if original_path:
                    # ntpath 语义适用于 Windows 路径，即使原始路径含反斜杠。
                    import ntpath
                    name = ntpath.basename(original_path.rstrip("\\/")) or original_path
                else:
                    # 元数据缺失时仍保留统一字段；不伪造原始路径或删除时间。
                    name = entry.name

                if is_dir:
                    size_bytes = directory_file_bytes(r_path)
                else:
                    size_bytes = st.st_size

                rows.append({
                    "name": name,
                    "type": "directory" if is_dir else "file",
                    "original_path": original_path,
                    "trash_path": os.path.abspath(os.fspath(r_path)),
                    "deleted_at": deleted_at,
                    "size": human_readable_size(size_bytes),
                })
    except FileNotFoundError:
        # 此卷没有为当前用户创建回收站目录，正常跳过。
        return
    except OSError as exc:
        print(f"无法遍历回收站 {recycle_dir}: {exc}", file=sys.stderr)


def main():
    if os.name != "nt":
        print("此脚本只能在 Windows 上运行。", file=sys.stderr)
        raise SystemExit(1)

    try:
        sid = current_user_sid()
    except (OSError, RuntimeError) as exc:
        print(f"无法获取当前用户 SID: {exc}", file=sys.stderr)
        raise SystemExit(1)

    rows = []
    for root in volume_roots():
        recycle_dir = root / "$Recycle.Bin" / sid
        scan_recycle_bin(recycle_dir, rows)

    rows.sort(key=lambda item: item["deleted_at"] or "", reverse=True)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()