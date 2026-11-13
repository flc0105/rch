SCRIPT_METADATA = {
    "name": "win/system/token_info_full",
    "display_name": "Full Token Information",
    "description": "Inspect the current process token security context.",
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
TokenRestrictedSids = 11
TokenElevationType = 18
TokenElevation = 20
TokenHasRestrictions = 21
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


class TOKEN_USER(ctypes.Structure):
    _fields_ = [("User", SID_AND_ATTRIBUTES)]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


class TOKEN_ELEVATION(ctypes.Structure):
    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


# 显式声明 argtypes / restype，避免 64 位句柄截断。
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
        try:
            return str_ptr.value
        finally:
            kernel32.LocalFree(ctypes.cast(str_ptr, wintypes.HLOCAL))
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


def _get_token_info(handle, info_class):
    """保留原始缓冲区，直到其中的 SID 指针完成转换。"""
    size = wintypes.DWORD(0)
    advapi32.GetTokenInformation(handle, info_class, None, 0, ctypes.byref(size))
    if size.value == 0:
        raise ctypes.WinError(ctypes.get_last_error())

    buf = ctypes.create_string_buffer(size.value)
    if not advapi32.GetTokenInformation(
        handle, info_class, buf, size.value, ctypes.byref(size)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return buf


def _sid_attributes(attributes):
    flags = []
    # Logon ID is a combined two-bit flag.
    if (attributes & 0xC0000000) == 0xC0000000:
        flags.append("Logon ID")
        attributes &= ~0xC0000000
    for bit, name in (
        (0x1, "Mandatory"),
        (0x2, "Enabled by default"),
        (0x4, "Enabled"),
        (0x8, "Owner"),
        (0x10, "Deny only"),
        (0x20, "Integrity"),
        (0x40, "Integrity enabled"),
        (0x20000000, "Resource"),
    ):
        if attributes & bit:
            flags.append(name)
            attributes &= ~bit
    if attributes:
        flags.append(hex(attributes))
    return ", ".join(flags) if flags else "None"


def _token_sids(handle, info_class):
    buf = _get_token_info(handle, info_class)
    count = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD)).contents.value
    if count == 0:
        return []
    offset = TOKEN_GROUPS.Groups.offset
    item_size = ctypes.sizeof(SID_AND_ATTRIBUTES)
    if len(buf) < offset or count > (len(buf) - offset) // item_size:
        raise ValueError("Invalid SID array size")
    entries = ctypes.cast(
        ctypes.addressof(buf) + offset,
        ctypes.POINTER(SID_AND_ATTRIBUTES * count),
    ).contents
    return [{
        "sid": _sid_to_string(entry.Sid),
        "attributes": _sid_attributes(entry.Attributes),
        "enabled": bool(entry.Attributes & 0x4),
        "mandatory": bool(entry.Attributes & 0x1),
        "use_for_deny_only": bool(entry.Attributes & 0x10),
    } for entry in entries]


def dump_token():
    process = kernel32.GetCurrentProcess()
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(process, TOKEN_READ, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())

    result = {}
    try:
        try:
            buf = _get_token_info(token, TokenIntegrityLevel)
            label = ctypes.cast(buf, ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents
            result["TokenIntegrityLevel"] = _integrity_level_name(label.Label.Sid)
        except Exception as e:
            result["TokenIntegrityLevel"] = {"error": str(e)}

        try:
            buf = _get_token_info(token, TokenElevationType)
            et = ctypes.cast(buf, ctypes.POINTER(ctypes.c_int)).contents.value
            result["TokenElevationType"] = {1: "Default", 2: "Full", 3: "Limited"}.get(et, str(et))
        except Exception as e:
            result["TokenElevationType"] = {"error": str(e)}

        try:
            buf = _get_token_info(token, TokenElevation)
            elev = ctypes.cast(buf, ctypes.POINTER(TOKEN_ELEVATION)).contents
            result["TokenElevation"] = bool(elev.TokenIsElevated)
        except Exception as e:
            result["TokenElevation"] = {"error": str(e)}

        try:
            result["TokenGroups"] = _token_sids(token, TokenGroups)
        except Exception as e:
            result["TokenGroups"] = {"error": str(e)}

        for info_class, name in (
            (TokenIsAppContainer, "TokenIsAppContainer"),
            (TokenVirtualizationAllowed, "TokenVirtualizationAllowed"),
        ):
            try:
                buf = _get_token_info(token, info_class)
                result[name] = bool(ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD)).contents.value)
            except Exception as e:
                result[name] = {"error": str(e)}

        try:
            buf = _get_token_info(token, TokenStatistics)
            stats = ctypes.cast(buf, ctypes.POINTER(TOKEN_STATISTICS)).contents
            result["TokenType"] = "Primary" if stats.TokenType == 1 else "Impersonation"
            result["GroupCount"] = stats.GroupCount
            result["AuthenticationId"] = f"{stats.AuthenticationId.HighPart:08x}-{stats.AuthenticationId.LowPart:08x}"
            result["TokenId"] = f"{stats.TokenId.HighPart:08x}-{stats.TokenId.LowPart:08x}"
        except Exception as e:
            result["TokenStatistics"] = {"error": str(e)}

        try:
            buf = _get_token_info(token, TokenUser)
            user = ctypes.cast(buf, ctypes.POINTER(TOKEN_USER)).contents
            result["TokenUser"] = _sid_to_string(user.User.Sid)
        except Exception as e:
            result["TokenUser"] = {"error": str(e)}

        try:
            buf = _get_token_info(token, TokenHasRestrictions)
            result["TokenHasRestrictions"] = bool(
                ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD)).contents.value
            )
        except Exception as e:
            result["TokenHasRestrictions"] = {"error": str(e)}

        try:
            result["TokenRestrictedSids"] = _token_sids(token, TokenRestrictedSids)
        except Exception as e:
            result["TokenRestrictedSids"] = {"error": str(e)}
    finally:
        kernel32.CloseHandle(token)
    return result


def main():
    try:
        print(json.dumps(dump_token(), ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))


if __name__ == "__main__":
    main()