SCRIPT_METADATA = {
    "name": "win/system/token_info_full",
    "display_name": "Full Token Information",
    "description": "Dump TokenStatistics, TokenGroups, TokenIntegrityLevel, TokenElevationType, TokenVirtualizationAllowed, TokenIsAppContainer and more from the current process token.",
    "platforms": ["win"],
    "category": "System",
    "params": []
}

import ctypes
from ctypes import wintypes
import json
import sys

if sys.platform != "win32":
    raise RuntimeError("Windows only")

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

TOKEN_QUERY = 0x0008
TOKEN_READ = 0x00020008

TokenUser = 1
TokenGroups = 2
TokenOwner = 4
TokenStatistics = 10
TokenElevationType = 18
TokenElevation = 20
TokenVirtualizationAllowed = 23
TokenIntegrityLevel = 25
TokenIsAppContainer = 29


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class TOKEN_STATISTICS(ctypes.Structure):
    _fields_ = [
        ("TokenId", LUID),
        ("AuthenticationId", LUID),
        ("ExpirationTime", ctypes.c_longlong),
        ("TokenType", wintypes.DWORD),
        ("ImpersonationLevel", wintypes.DWORD),
        ("DynamicCharged", wintypes.DWORD),
        ("DynamicAvailable", wintypes.DWORD),
        ("GroupCount", wintypes.DWORD),
        ("PrivilegeCount", wintypes.DWORD),
        ("ModifiedId", LUID),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]


class TOKEN_GROUPS(ctypes.Structure):
    _fields_ = [("GroupCount", wintypes.DWORD), ("Groups", SID_AND_ATTRIBUTES * 1)]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


class TOKEN_ELEVATION(ctypes.Structure):
    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


# ===== 关键修复：显式声明 argtypes / restype，避免 64 位句柄截断 =====

kernel32.GetCurrentProcess.argtypes = []
kernel32.GetCurrentProcess.restype = wintypes.HANDLE

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
kernel32.LocalFree.restype = wintypes.HLOCAL

advapi32.OpenProcessToken.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)
]
advapi32.OpenProcessToken.restype = wintypes.BOOL

advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
]
advapi32.GetTokenInformation.restype = wintypes.BOOL

advapi32.ConvertSidToStringSidW.argtypes = [
    wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)
]
advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL


def _sid_to_string(sid_ptr):
    if not sid_ptr:
        return None
    str_ptr = wintypes.LPWSTR()
    if advapi32.ConvertSidToStringSidW(sid_ptr, ctypes.byref(str_ptr)):
        result = str_ptr.value
        kernel32.LocalFree(str_ptr)
        return result
    return None


def _integrity_level_name(sid_ptr):
    sid_str = _sid_to_string(sid_ptr)
    if not sid_str:
        return None
    mapping = {
        "S-1-16-0": "Untrusted",
        "S-1-16-4096": "Low",
        "S-1-16-8192": "Medium",
        "S-1-16-8448": "Medium Plus",
        "S-1-16-12288": "High",
        "S-1-16-16384": "System",
        "S-1-16-20480": "Protected Process",
    }
    return mapping.get(sid_str, sid_str)


def _get_token_info(handle, info_class, struct_type=None):
    """先拿 size，再拿数据。句柄是有效 HANDLE（已声明 argtypes）。"""
    size = wintypes.DWORD(0)
    advapi32.GetTokenInformation(handle, info_class, None, 0, ctypes.byref(size))
    if size.value == 0:
        # 第一次调用失败且没有拿到所需长度：句柄/类本身有问题
        raise ctypes.WinError(ctypes.get_last_error())

    buf = ctypes.create_string_buffer(size.value)
    if not advapi32.GetTokenInformation(
        handle, info_class, buf, size.value, ctypes.byref(size)
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    if struct_type:
        return ctypes.cast(buf, ctypes.POINTER(struct_type)).contents
    return buf


def _dump_token_groups(handle):
    groups = []
    try:
        size = wintypes.DWORD(0)
        advapi32.GetTokenInformation(handle, TokenGroups, None, 0, ctypes.byref(size))
        if size.value == 0:
            raise ctypes.WinError(ctypes.get_last_error())

        buf = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            handle, TokenGroups, buf, size.value, ctypes.byref(size)
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        tg = ctypes.cast(buf, ctypes.POINTER(TOKEN_GROUPS)).contents
        for i in range(tg.GroupCount):
            entry = tg.Groups[i]
            groups.append({
                "sid": _sid_to_string(entry.Sid),
                "attributes": hex(entry.Attributes),
                "enabled": bool(entry.Attributes & 0x4),
                "mandatory": bool(entry.Attributes & 0x1),
                "use_for_deny_only": bool(entry.Attributes & 0x10),
            })
    except Exception as e:
        groups.append({"error": str(e)})
    return groups


def dump_token():
    process = kernel32.GetCurrentProcess()
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(process, TOKEN_READ, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())

    result = {}

    try:
        stats = _get_token_info(token, TokenStatistics, TOKEN_STATISTICS)
        result["TokenStatistics"] = {
            "TokenId": f"{stats.TokenId.HighPart:08x}-{stats.TokenId.LowPart:08x}",
            "AuthenticationId": f"{stats.AuthenticationId.HighPart:08x}-{stats.AuthenticationId.LowPart:08x}",
            "TokenType": "Primary" if stats.TokenType == 1 else "Impersonation",
            "ImpersonationLevel": stats.ImpersonationLevel,
            "DynamicCharged": stats.DynamicCharged,
            "DynamicAvailable": stats.DynamicAvailable,
            "GroupCount": stats.GroupCount,
            "PrivilegeCount": stats.PrivilegeCount,
        }
    except Exception as e:
        result["TokenStatistics"] = {"error": str(e)}

    result["TokenGroups"] = _dump_token_groups(token)

    try:
        label = _get_token_info(token, TokenIntegrityLevel, TOKEN_MANDATORY_LABEL)
        result["TokenIntegrityLevel"] = {
            "sid": _sid_to_string(label.Label.Sid),
            "name": _integrity_level_name(label.Label.Sid),
        }
    except Exception as e:
        result["TokenIntegrityLevel"] = {"error": str(e)}

    try:
        buf = _get_token_info(token, TokenElevationType)
        et = ctypes.cast(buf, ctypes.POINTER(ctypes.c_int)).contents.value
        names = {1: "Default", 2: "Full", 3: "Limited"}
        result["TokenElevationType"] = {
            "value": et,
            "name": names.get(et, str(et)),
        }
    except Exception as e:
        result["TokenElevationType"] = {"error": str(e)}

    try:
        buf = _get_token_info(token, TokenVirtualizationAllowed)
        result["TokenVirtualizationAllowed"] = bool(
            ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD)).contents.value
        )
    except Exception as e:
        result["TokenVirtualizationAllowed"] = {"error": str(e)}

    try:
        buf = _get_token_info(token, TokenIsAppContainer)
        result["TokenIsAppContainer"] = bool(
            ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD)).contents.value
        )
    except Exception as e:
        result["TokenIsAppContainer"] = {"error": str(e)}

    try:
        elev = _get_token_info(token, TokenElevation, TOKEN_ELEVATION)
        result["TokenElevation"] = bool(elev.TokenIsElevated)
    except Exception as e:
        result["TokenElevation"] = {"error": str(e)}

    kernel32.CloseHandle(token)
    return result


def main():
    try:
        print(json.dumps(dump_token(), ensure_ascii=False, indent=2, default=str))
    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))


if __name__ == "__main__":
    main()