SCRIPT_METADATA = {
    "name": "mac/browser/get_chromium_bookmarks",
    "display_name": "Chromium Bookmarks",
    "description": "Retrieve bookmarks from Chrome or Edge.",
    "platforms": ["common"],
    "category": "Browser",
    "params": [
        {
            "name": "browser",
            "type": "select",
            "required": False,
            "default": "chrome",
            "options": ["chrome", "edge"],
            "description": "Browser (Chrome or Edge)"
        }
    ]
}

import os
import json
import sys
from pathlib import Path
from datetime import datetime


def chrome_time_to_datetime(chrome_time):
    if chrome_time in (None, "", 0, "0"):
        return None

    try:
        chrome_time = int(chrome_time)
        unix_timestamp = (chrome_time / 1000000) - 11644473600
        return datetime.fromtimestamp(unix_timestamp)
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def get_browser_data_dir(browser):
    home = Path.home()

    paths = {
        "chrome": {
            "win": home / "AppData/Local/Google/Chrome/User Data",
            "darwin": home / "Library/Application Support/Google/Chrome",
            "linux": home / ".config/google-chrome",
        },
        "edge": {
            "win": home / "AppData/Local/Microsoft/Edge/User Data",
            "darwin": home / "Library/Application Support/Microsoft Edge",
            "linux": home / ".config/microsoft-edge",
        },
    }

    if sys.platform == "win32":
        platform_key = "win"
    elif sys.platform == "darwin":
        platform_key = "darwin"
    else:
        platform_key = "linux"

    return str(paths.get(browser.lower(), {}).get(platform_key, "")) or None


def find_profile_dir(profile_path):
    for name in ["Default", "Profile 1", "Profile 2", "Profile 3"]:
        candidate = os.path.join(profile_path, name)
        if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "Bookmarks")):
            return candidate
    return None


def extract_bookmarks_recursive(node, path=""):
    bookmarks = []

    if node.get("type") == "folder":
        folder_name = node.get("name", "Unnamed Folder")
        current_path = f"{path}/{folder_name}" if path else folder_name
        for child in node.get("children", []):
            bookmarks.extend(extract_bookmarks_recursive(child, current_path))

    elif node.get("type") == "url":
        dt = chrome_time_to_datetime(node.get("date_added"))
        added_time = dt.isoformat(timespec="seconds") if dt else None

        bookmarks.append({
            "title": node.get("name", ""),
            "url": node.get("url", ""),
            "path": path,
            "time": added_time
        })

    return bookmarks


def get_chromium_bookmarks(filename):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)

        roots = data.get("roots", {})
        all_bookmarks = []

        root_mappings = [
            ("bookmark_bar", "Bookmarks Bar"),
            ("other", "Other Bookmarks"),
            ("synced", "Mobile Bookmarks"),
        ]

        for root_key, root_label in root_mappings:
            root_node = roots.get(root_key, {})
            for child in root_node.get("children", []):
                all_bookmarks.extend(extract_bookmarks_recursive(child, root_label))

        return all_bookmarks

    except Exception as exc:
        return {"error": f"Failed to read bookmarks: {exc}"}


def extract_bookmarks(browser="chrome"):
    browser = (browser or "chrome").lower()
    if browser not in ("chrome", "edge"):
        return {"error": f"Unsupported browser: {browser}"}

    profile_path = get_browser_data_dir(browser)
    if not profile_path or not os.path.isdir(profile_path):
        return {"error": f"Browser not found: {browser}"}

    profile_dir = find_profile_dir(profile_path)
    if not profile_dir:
        return {"error": "Bookmarks file not found"}

    return get_chromium_bookmarks(os.path.join(profile_dir, "Bookmarks"))


try:
    browser = kwargs.get("browser", "chrome")
    print(json.dumps(extract_bookmarks(browser), indent=2, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False))
