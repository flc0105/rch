SCRIPT_METADATA = {
    "name": "win/system/wer_report",
    "display_name": "WER Report",
    "description": "Trigger a Windows Error Reporting submission",
    "platforms": ["windows"],
    "category": "UI",
    "params": [
        {
            "name": "exec_path",
            "type": "string",
            "required": False,
            "default": r"C:\windows\explorer.exe",
            "description": "Target executable path used in the report"
        }
    ]
}

import ctypes
import threading
from ctypes import wintypes

import win32process


class WER_REPORT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('dwSize', wintypes.DWORD),
        ('hProcess', wintypes.HANDLE),
        ('wzConsentKey', wintypes.WCHAR * 64),
        ('wzFriendlyEventName', wintypes.WCHAR * 128),
        ('wzApplicationName', wintypes.WCHAR * 128),
        ('wzApplicationPath', wintypes.WCHAR * wintypes.MAX_PATH),
        ('wzDescription', wintypes.WCHAR * 512),
        ('hwndParent', wintypes.HWND)
    ]


def report_error(exec_path):
    handle_report = wintypes.HANDLE()

    wri = WER_REPORT_INFORMATION()
    wri.dwSize = ctypes.sizeof(wri)
    wri.hProcess = win32process.GetCurrentProcess()
    wri.wzApplicationPath = exec_path

    wer = ctypes.windll.wer

    wer.WerReportCreate('pwzEventType', 3, ctypes.byref(wri), ctypes.byref(handle_report))
    wer.WerReportSetUIOption(handle_report, 2, exec_path)
    wer.WerReportSubmit(handle_report, 4, 0, ctypes.byref(wri))
    wer.WerReportCloseHandle(handle_report)


exec_path = kwargs.get('exec_path', r'C:\windows\explorer.exe')

threading.Thread(target=report_error, args=(exec_path,), daemon=True).start()
