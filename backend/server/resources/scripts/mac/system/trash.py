#!/usr/bin/env python3
"""将当前用户的 macOS 废纸篓条目输出为 JSON 数组；仅使用标准库。"""
import ctypes
import datetime as dt
import json
import os
import stat
import struct
import sys
from pathlib import Path


# ---- 读取 Finder 存在 .DS_Store 内的“放回原处”路径 ----
class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, count):
        if count < 0 or self.pos + count > len(self.data):
            raise ValueError(".DS_Store 数据不完整")
        value = self.data[self.pos:self.pos + count]
        self.pos += count
        return value

    def u32(self):
        return struct.unpack(">I", self.take(4))[0]


def read_putback(trash_dir):
    """返回 {废纸篓中名称: {'ptbL': 原始父目录, 'ptbN': 原始名称}}。"""
    store_path = trash_dir / ".DS_Store"
    try:
        data = store_path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        print(f"无法读取 {store_path}: {exc}", file=sys.stderr)
        return {}

    try:
        if len(data) < 36 or data[:8] != b"\x00\x00\x00\x01Bud1":
            raise ValueError("无效的 .DS_Store 文件头")
        root_offset, root_size, root_copy = struct.unpack_from(">III", data, 8)
        if root_offset != root_copy:
            raise ValueError(".DS_Store 数据块索引不一致")

        def block(offset, length):
            start = offset + 4  # Bud1 的地址相对文件头后 4 字节
            if start < 0 or start + length > len(data):
                raise ValueError(".DS_Store 数据块越界")
            return data[start:start + length]

        root = Reader(block(root_offset, root_size))
        count = root.u32()
        root.u32()  # 保留字段
        if count > len(root.data) // 4:
            raise ValueError(".DS_Store 索引数量异常")
        offsets = [root.u32() for _ in range(count)]
        for _ in range((-count) % 256):
            root.u32()  # 索引表填充到 256 的整数倍

        toc_count = root.u32()
        master_id = None
        for _ in range(toc_count):
            key_len = root.take(1)[0]
            key = root.take(key_len)
            value = root.u32()
            if key == b"DSDB":
                master_id = value
        if master_id is None:
            return {}

        def by_id(block_id):
            if block_id >= len(offsets):
                raise ValueError(".DS_Store 数据块 ID 无效")
            entry = offsets[block_id]
            return Reader(block(entry & ~31, 1 << (entry & 31)))

        master = by_id(master_id)
        root_id = master.u32()
        master.u32()  # B 树层数
        master.u32()  # 记录总数
        node_count = master.u32()
        result, visited, stack = {}, set(), [root_id]

        while stack:
            node_id = stack.pop()
            if node_id in visited:
                continue
            visited.add(node_id)
            if len(visited) > max(1024, node_count * 2):
                raise ValueError(".DS_Store B 树节点数量异常")
            node = by_id(node_id)
            next_node, record_count = node.u32(), node.u32()
            for _ in range(record_count):
                if next_node:
                    stack.append(node.u32())  # 内部节点的子树
                name = node.take(node.u32() * 2).decode("utf-16-be", "replace")
                code, value_type = node.take(4), node.take(4)
                value = None
                if value_type == b"ustr":
                    value = node.take(node.u32() * 2).decode("utf-16-be", "replace")
                elif value_type == b"blob":
                    node.take(node.u32())
                elif value_type == b"bool":
                    node.take(1)
                elif value_type in (b"long", b"shor", b"type"):
                    node.take(4)
                elif value_type in (b"comp", b"dutc"):
                    node.take(8)
                else:
                    raise ValueError(f"不支持的 .DS_Store 记录类型: {value_type!r}")
                if code in (b"ptbL", b"ptbN") and value is not None:
                    result.setdefault(name, {})[code.decode("ascii")] = value
            if next_node:
                stack.append(next_node)
        return result
    except (ValueError, struct.error) as exc:
        print(f"无法解析 {store_path}: {exc}", file=sys.stderr)
        return {}


def original_path(item_name, record, trash_dir):
    """无法确定原始父路径时返回 None，绝不以废纸篓路径冒充。"""
    parent = record.get("ptbL")
    if not parent:
        return None
    # Finder 在 APFS 上可能写入系统内部 firmlink 路径。
    parent = parent.lstrip("/")
    if parent.startswith("System/Volumes/Data/"):
        parent = parent[len("System/Volumes/Data/"):]
    elif parent == "System/Volumes/Data":
        parent = ""

    # 外接卷的 ptbL 可能是卷内相对路径。
    parts = trash_dir.parts
    if len(parts) >= 5 and parts[1] == "Volumes" and parts[3] in (".Trashes",):
        volume_root = Path("/") / parts[1] / parts[2]
        if not parent.startswith(("Volumes/", "System/Volumes/", "Users/")):
            parent = str(volume_root / parent).lstrip("/")

    name = record.get("ptbN") or item_name
    if name in ("", ".", "..") or "/" in name or "\x00" in name:
        return None
    return os.path.normpath("/" + parent.rstrip("/") + "/" + name)


# ---- 通过 macOS 原生 getattrlist 读取“加入当前文件夹的时间” ----
class AttrList(ctypes.Structure):
    _fields_ = [
        ("bitmapcount", ctypes.c_uint16), ("reserved", ctypes.c_uint16),
        ("commonattr", ctypes.c_uint32), ("volattr", ctypes.c_uint32),
        ("dirattr", ctypes.c_uint32), ("fileattr", ctypes.c_uint32),
        ("forkattr", ctypes.c_uint32),
    ]


try:
    _libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    _getattrlist = _libc.getattrlist
    _getattrlist.argtypes = [ctypes.c_char_p, ctypes.POINTER(AttrList),
                             ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong]
    _getattrlist.restype = ctypes.c_int
except (OSError, AttributeError):
    _getattrlist = None


def trash_time(path, st):
    added = None
    if _getattrlist is not None:
        # ATTR_CMN_RETURNED_ATTRS | ATTR_CMN_ADDEDTIME
        req = AttrList(5, 0, 0x80000000 | 0x10000000, 0, 0, 0, 0)
        out = ctypes.create_string_buffer(64)
        try:
            success = _getattrlist(os.fsencode(path), ctypes.byref(req),
                                   out, ctypes.sizeof(out), 1)  # NOFOLLOW
            if success == 0:
                length = struct.unpack_from("=I", out.raw, 0)[0]
                returned_common = struct.unpack_from("=I", out.raw, 4)[0]
                if length >= 40 and returned_common & 0x10000000:
                    sec, nsec = struct.unpack_from("=qq", out.raw, 24)
                    if sec > 0 and 0 <= nsec < 1_000_000_000:
                        added = sec + nsec / 1_000_000_000
        except (OSError, OverflowError, ValueError):
            pass
    # 不支持 Date Added 的卷：ctime 只是最近元数据变化时间，作为近似值。
    timestamp = added if added is not None else st.st_ctime
    return dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def file_bytes(path):
    """目录累计普通文件的逻辑字节数，不跟随符号链接。无法完整读取则返回 None。"""
    total, stack = 0, [path]
    try:
        while stack:
            with os.scandir(stack.pop()) as entries:
                for item in entries:
                    info = item.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        stack.append(item.path)
                    elif stat.S_ISREG(info.st_mode):
                        total += info.st_size
        return total
    except OSError as exc:
        print(f"无法完整计算目录大小 {path}: {exc}", file=sys.stderr)
        return None


def human_readable_size(size_bytes):
    """将字节数格式化为 B/KB/MB/GB/TB/PB；无法计算时保留 None。"""
    if size_bytes is None:
        return None
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.2f} {unit}"
        size /= 1024


def trash_locations():
    locations = [Path.home() / ".Trash"]
    uid = str(os.getuid())
    try:
        with os.scandir("/Volumes") as volumes:
            for v in volumes:
                if v.is_dir(follow_symlinks=False) and os.path.ismount(v.path):
                    locations.append(Path(v.path) / ".Trashes" / uid)
    except OSError:
        pass
    # 去重：不跟随文件内容的链接，仅对废纸篓根路径做规范化。
    seen = set()
    for location in locations:
        if location.is_dir():
            real = os.path.realpath(location)
            if real not in seen:
                seen.add(real)
                yield location


def main():
    rows = []
    for trash in trash_locations():
        records = read_putback(trash)
        try:
            with os.scandir(trash) as entries:
                for entry in entries:
                    if entry.name in (".DS_Store", ".localized"):
                        continue
                    try:
                        st = entry.stat(follow_symlinks=False)
                        is_dir = stat.S_ISDIR(st.st_mode)
                        record = records.get(entry.name, {})
                        rows.append({
                            "name": record.get("ptbN") or entry.name,
                            "type": "directory" if is_dir else "file",
                            "original_path": original_path(entry.name, record, trash),
                            "trash_path": os.path.abspath(entry.path),
                            "deleted_at": trash_time(entry.path, st),
                            "size": human_readable_size(file_bytes(entry.path) if is_dir else st.st_size),
                        })
                    except OSError as exc:
                        print(f"读取失败 {entry.path}: {exc}", file=sys.stderr)
        except OSError as exc:
            print(f"无法遍历废纸篓 {trash}: {exc}", file=sys.stderr)
    rows.sort(key=lambda item: item["deleted_at"], reverse=True)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()