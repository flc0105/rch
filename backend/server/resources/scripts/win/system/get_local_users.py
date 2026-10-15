SCRIPT_METADATA = {
    "name": "win/system/get_local_users",
    "display_name": "Local Users",
    "description": "List local Windows user accounts and their security status.",
    "platforms": ["win"],
    "category": "System",
    "params": []
}

import json
import ctypes
from ctypes import wintypes

try:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    netapi32 = ctypes.WinDLL("netapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
except Exception:
    print('{"error": "Windows platform support is required."}')
    raise SystemExit(1)


FILTER_NORMAL_ACCOUNT = 0x0002
MAX_PREFERRED_LENGTH = 0xFFFFFFFF
NERR_Success = 0
ERROR_MORE_DATA = 234

UF_ACCOUNTDISABLE = 0x0002
UF_LOCKOUT = 0x0010
UF_PASSWD_NOTREQD = 0x0020
UF_PASSWD_CANT_CHANGE = 0x0040
UF_DONT_EXPIRE_PASSWD = 0x10000
UF_PASSWORD_EXPIRED = 0x800000

SID_NAME_USE = {
    1: "User",
    2: "Group",
    3: "Domain",
    4: "Alias",
    5: "WellKnownGroup",
    6: "DeletedAccount",
    7: "Invalid",
    8: "Unknown",
    9: "Computer",
    10: "Label",
    11: "LogonSession"
}


class USER_INFO_3(ctypes.Structure):
    _fields_ = [
        ("usri3_name", wintypes.LPWSTR),
        ("usri3_password", wintypes.LPWSTR),
        ("usri3_password_age", wintypes.DWORD),
        ("usri3_priv", wintypes.DWORD),
        ("usri3_home_dir", wintypes.LPWSTR),
        ("usri3_comment", wintypes.LPWSTR),
        ("usri3_flags", wintypes.DWORD),
        ("usri3_script_path", wintypes.LPWSTR),
        ("usri3_auth_flags", wintypes.DWORD),
        ("usri3_full_name", wintypes.LPWSTR),
        ("usri3_usr_comment", wintypes.LPWSTR),
        ("usri3_parms", wintypes.LPWSTR),
        ("usri3_workstations", wintypes.LPWSTR),
        ("usri3_last_logon", wintypes.DWORD),
        ("usri3_last_logoff", wintypes.DWORD),
        ("usri3_acct_expires", wintypes.DWORD),
        ("usri3_max_storage", wintypes.DWORD),
        ("usri3_units_per_week", wintypes.DWORD),
        ("usri3_logon_hours", ctypes.POINTER(ctypes.c_ubyte)),
        ("usri3_bad_pw_count", wintypes.DWORD),
        ("usri3_num_logons", wintypes.DWORD),
        ("usri3_logon_server", wintypes.LPWSTR),
        ("usri3_country_code", wintypes.DWORD),
        ("usri3_code_page", wintypes.DWORD),
        ("usri3_user_id", wintypes.DWORD),
        ("usri3_primary_group_id", wintypes.DWORD),
        ("usri3_profile", wintypes.LPWSTR),
        ("usri3_home_dir_drive", wintypes.LPWSTR),
        ("usri3_password_expired", wintypes.DWORD),
    ]


NetUserEnum = netapi32.NetUserEnum
NetUserEnum.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.LPBYTE),
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD)
]
NetUserEnum.restype = wintypes.DWORD

NetApiBufferFree = netapi32.NetApiBufferFree
NetApiBufferFree.argtypes = [wintypes.LPVOID]
NetApiBufferFree.restype = wintypes.DWORD

LookupAccountNameW = advapi32.LookupAccountNameW
LookupAccountNameW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.LPVOID,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD)
]
LookupAccountNameW.restype = wintypes.BOOL

ConvertSidToStringSidW = advapi32.ConvertSidToStringSidW
ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
ConvertSidToStringSidW.restype = wintypes.BOOL

LocalFree = kernel32.LocalFree
LocalFree.argtypes = [wintypes.HLOCAL]
LocalFree.restype = wintypes.HLOCAL


def get_computer_name():
    size = wintypes.DWORD(256)
    buf = ctypes.create_unicode_buffer(size.value)

    if kernel32.GetComputerNameW(buf, ctypes.byref(size)):
        return buf.value

    return ""


def sid_from_account(name):
    result = {
        "sid": "",
        "domain": "",
        "sid_type": ""
    }

    sid_size = wintypes.DWORD(0)
    domain_size = wintypes.DWORD(0)
    sid_type = wintypes.DWORD(0)

    LookupAccountNameW(
        None,
        name,
        None,
        ctypes.byref(sid_size),
        None,
        ctypes.byref(domain_size),
        ctypes.byref(sid_type)
    )

    if sid_size.value == 0:
        return result

    sid_buffer = ctypes.create_string_buffer(sid_size.value)
    domain_buffer = ctypes.create_unicode_buffer(domain_size.value + 1)

    ok = LookupAccountNameW(
        None,
        name,
        sid_buffer,
        ctypes.byref(sid_size),
        domain_buffer,
        ctypes.byref(domain_size),
        ctypes.byref(sid_type)
    )

    if not ok:
        return result

    string_sid = wintypes.LPWSTR()

    if ConvertSidToStringSidW(sid_buffer, ctypes.byref(string_sid)):
        result["sid"] = string_sid.value
        LocalFree(string_sid)

    result["domain"] = domain_buffer.value
    result["sid_type"] = SID_NAME_USE.get(sid_type.value, str(sid_type.value))

    return result


def bool_flag(flags, bit):
    return bool(flags & bit)


def enum_local_users():
    rows = []
    resume_handle = wintypes.DWORD(0)

    while True:
        buffer = wintypes.LPBYTE()
        entries_read = wintypes.DWORD(0)
        total_entries = wintypes.DWORD(0)

        status = NetUserEnum(
            None,
            3,
            FILTER_NORMAL_ACCOUNT,
            ctypes.byref(buffer),
            MAX_PREFERRED_LENGTH,
            ctypes.byref(entries_read),
            ctypes.byref(total_entries),
            ctypes.byref(resume_handle)
        )

        if status not in (NERR_Success, ERROR_MORE_DATA):
            break

        if entries_read.value and buffer:
            array_type = USER_INFO_3 * entries_read.value
            users = ctypes.cast(buffer, ctypes.POINTER(array_type)).contents

            for user in users:
                name = user.usri3_name or ""
                sid_info = sid_from_account(name)

                item = {
                    "name": name,
                    "account": (sid_info["domain"] + "\\" + name) if sid_info["domain"] else name,
                    "sid": sid_info["sid"],
                    "full_name": user.usri3_full_name or "",
                    "disabled": bool_flag(user.usri3_flags, UF_ACCOUNTDISABLE),
                    "locked": bool_flag(user.usri3_flags, UF_LOCKOUT),
                    "password_not_required": bool_flag(user.usri3_flags, UF_PASSWD_NOTREQD),
                    "password_never_expires": bool_flag(user.usri3_flags, UF_DONT_EXPIRE_PASSWD),
                    "password_expired": bool_flag(user.usri3_flags, UF_PASSWORD_EXPIRED) or bool(user.usri3_password_expired),
                }

                rows.append(item)

        if buffer:
            NetApiBufferFree(buffer)

        if status != ERROR_MORE_DATA:
            break

    return rows


result = enum_local_users()

result.sort(key=lambda item: item["account"].casefold())

print(json.dumps(result, ensure_ascii=False, indent=2))