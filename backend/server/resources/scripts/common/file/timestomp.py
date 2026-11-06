SCRIPT_METADATA = {
    "name": "common/file/timestomp",
    "display_name": "Timestomp",
    "description": "Modify file access, modification and creation/change times.",
    "platforms": ["win", "mac", "linux"],
    "category": "File",
    "params": [
        {
            "name": "selected_path",
            "label": "Remote path",
            "type": "remote_file",
            "description": "Target file whose timestamps will be modified.",
            "required": True,
        },
        {
            "name": "atime",
            "label": "Access time",
            "type": "string",
            "description": "New access time. Formats: 'YYYY-MM-DD HH:MM:SS', 'YYYY-MM-DD', Unix timestamp, or 'now'. Leave empty to skip.",
            "required": False,
            "default": "",
        },
        {
            "name": "mtime",
            "label": "Modify time",
            "type": "string",
            "description": "New modification time. Same formats as access time. Leave empty to skip.",
            "required": False,
            "default": "",
        },
        {
            "name": "ctime",
            "label": "Create/Change time",
            "type": "string",
            "description": "Windows/macOS: creation time. Linux: ctime cannot be set from user space. Same formats as access time.",
            "required": False,
            "default": "",
        },
    ],
}

import ctypes
from ctypes import wintypes
import json
import os
import sys
import time

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
)


def parse_time(value):
    """把字符串解析成 epoch 秒；空字符串/None 返回 None。"""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if value.lower() == "now":
        return time.time()
    if value.isdigit() and len(value) <= 11:
        return float(value)
    for fmt in TIME_FORMATS:
        try:
            return time.mktime(time.strptime(value, fmt))
        except ValueError:
            continue
    raise ValueError(f"unrecognized time format: {value!r}")


def _unix_to_filetime(ts):
    """epoch 秒 -> Windows FILETIME（100ns 间隔，1601-01-01 起）。"""
    intervals = int((ts + 11644473600) * 10_000_000)
    ft = FILETIME()
    ft.dwLowDateTime = intervals & 0xFFFFFFFF
    ft.dwHighDateTime = (intervals >> 32) & 0xFFFFFFFF
    return ft


# ============================================================
# Windows
# ============================================================

if IS_WINDOWS:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    FILE_WRITE_ATTRIBUTES = 0x0100
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE

    kernel32.SetFileTime.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
    ]
    kernel32.SetFileTime.restype = wintypes.BOOL

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    def _win_set_times(path, atime=None, mtime=None, ctime=None):
        handle = kernel32.CreateFileW(
            path,
            FILE_WRITE_ATTRIBUTES,
            0,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if handle in (None, INVALID_HANDLE_VALUE):
            raise ctypes.WinError(ctypes.get_last_error())

        try:
            atime_ft = _unix_to_filetime(atime) if atime is not None else None
            mtime_ft = _unix_to_filetime(mtime) if mtime is not None else None
            ctime_ft = _unix_to_filetime(ctime) if ctime is not None else None

            p_atime = ctypes.byref(atime_ft) if atime_ft is not None else None
            p_mtime = ctypes.byref(mtime_ft) if mtime_ft is not None else None
            p_ctime = ctypes.byref(ctime_ft) if ctime_ft is not None else None

            # SetFileTime(hFile, lpCreationTime, lpLastAccessTime, lpLastWriteTime)
            ok = kernel32.SetFileTime(handle, p_ctime, p_atime, p_mtime)
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel32.CloseHandle(handle)


# ============================================================
# macOS
# ============================================================

if IS_MACOS:
    libc = ctypes.CDLL(
        "/usr/lib/libSystem.B.dylib", use_errno=True
    )

    ATTR_BIT_MAP_COUNT = 5
    ATTR_CMN_CRTIME = 0x00000200

    class AttrList(ctypes.Structure):
        _fields_ = [
            ("bitmapcount", ctypes.c_ushort),
            ("reserved", ctypes.c_ushort),
            ("commonattr", ctypes.c_uint32),
            ("volattr", ctypes.c_uint32),
            ("dirattr", ctypes.c_uint32),
            ("fileattr", ctypes.c_uint32),
            ("forkattr", ctypes.c_uint32),
        ]

    class Timespec(ctypes.Structure):
        _fields_ = [
            ("tv_sec", ctypes.c_long),
            ("tv_nsec", ctypes.c_long),
        ]

    libc.setattrlist.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(AttrList),
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_ulong,
    ]
    libc.setattrlist.restype = ctypes.c_int

    def _mac_set_birthtime(path, ts):
        attrlist = AttrList()
        attrlist.bitmapcount = ATTR_BIT_MAP_COUNT
        attrlist.commonattr = ATTR_CMN_CRTIME

        ts_obj = Timespec()
        ts_obj.tv_sec = int(ts)
        ts_obj.tv_nsec = int((ts - int(ts)) * 1_000_000_000)

        buf = ctypes.create_string_buffer(ctypes.sizeof(ts_obj))
        ctypes.memmove(buf, ctypes.byref(ts_obj), ctypes.sizeof(ts_obj))

        ret = libc.setattrlist(
            path.encode("utf-8", "surrogateescape"),
            ctypes.byref(attrlist),
            buf,
            ctypes.sizeof(ts_obj),
            0,
        )
        if ret != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno), path)

    def _mac_set_times(path, atime=None, mtime=None, ctime=None):
        st = os.stat(path)
        new_atime = atime if atime is not None else st.st_atime
        new_mtime = mtime if mtime is not None else st.st_mtime
        os.utime(path, (new_atime, new_mtime))
        if ctime is not None:
            _mac_set_birthtime(path, ctime)


# ============================================================
# Linux
# ============================================================

if IS_LINUX:
    def _linux_set_times(path, atime=None, mtime=None, ctime=None):
        if ctime is not None:
            # Linux 内核不允许用户空间修改 inode change time；
            # 调用 utime 只改 atime/mtime，ctime 仍会被内核刷新为当前时间。
            raise NotImplementedError(
                "Linux does not allow setting ctime (inode change time) "
                "from user space. Only atime and mtime can be modified."
            )
        st = os.stat(path)
        new_atime = atime if atime is not None else st.st_atime
        new_mtime = mtime if mtime is not None else st.st_mtime
        os.utime(path, (new_atime, new_mtime))


# ============================================================
# 统一入口
# ============================================================

def _apply(path, atime=None, mtime=None, ctime=None):
    if IS_WINDOWS:
        _win_set_times(path, atime=atime, mtime=mtime, ctime=ctime)
    elif IS_MACOS:
        _mac_set_times(path, atime=atime, mtime=mtime, ctime=ctime)
    elif IS_LINUX:
        _linux_set_times(path, atime=atime, mtime=mtime, ctime=ctime)
    else:
        raise RuntimeError(f"unsupported platform: {sys.platform}")


def main():
    result = {
        "path": None,
        "requested": {},
        "changed": [],
        "warnings": [],
        "errors": [],
    }

    try:
        path = kwargs["selected_path"]
        if not isinstance(path, str) or not path.strip():
            raise ValueError("selected_path must be a non-empty string")
        path = path.strip()
        result["path"] = path

        if not os.path.lexists(path):
            raise FileNotFoundError(path)

        raw_atime = kwargs.get("atime", "")
        raw_mtime = kwargs.get("mtime", "")
        raw_ctime = kwargs.get("ctime", "")

        atime = parse_time(raw_atime)
        mtime = parse_time(raw_mtime)
        ctime = parse_time(raw_ctime)

        result["requested"] = {
            "atime": atime,
            "mtime": mtime,
            "ctime": ctime,
        }

        if atime is None and mtime is None and ctime is None:
            raise ValueError("no timestamps specified; provide atime, mtime or ctime")

        # Linux 的 ctime 无法设置：提前给出警告，仍然尝试修改 atime/mtime
        linux_ctime_blocked = IS_LINUX and ctime is not None
        if linux_ctime_blocked:
            result["warnings"].append(
                "Linux: ctime (inode change time) cannot be set from user space; "
                "only atime/mtime will be modified."
            )
            ctime = None

        _apply(path, atime=atime, mtime=mtime, ctime=ctime)

        if atime is not None:
            result["changed"].append("atime")
        if mtime is not None:
            result["changed"].append("mtime")
        if ctime is not None:
            result["changed"].append("ctime")

        # 读取当前时间作为回执，便于校验
        st = os.stat(path)
        result["current"] = {
            "atime": st.st_atime,
            "mtime": st.st_mtime,
        }
        if hasattr(st, "st_birthtime"):
            result["current"]["birthtime"] = st.st_birthtime
        if hasattr(st, "st_ctime"):
            result["current"]["ctime_stat"] = st.st_ctime

        if linux_ctime_blocked:
            result["warnings"].append("ctime was not modified.")

    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()