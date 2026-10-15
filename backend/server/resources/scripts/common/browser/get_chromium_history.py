#!/usr/bin/env python3
"""
Chrome/Edge 历史记录提取模块
"""

SCRIPT_METADATA = {
    "name": "mac/browser/get_chromium_history",
    "display_name": "Chromium History",
    "description": "Retrieve browsing history from Chrome or Edge.",
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

import json
import os
import shutil
import sqlite3
import tempfile
import sys
from datetime import datetime
from pathlib import Path


def get_browser_data_dir(browser):
    """获取浏览器配置路径（跨平台）"""
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


def chrome_time_to_datetime(chrome_time):
    """
    将 Chrome 时间戳转换为 datetime 对象
    Chrome 时间戳是从 1601-01-01 开始的微秒数
    """
    if chrome_time in (None, "", 0, "0"):
        return None

    try:
        chrome_time = int(chrome_time)
        unix_timestamp = (chrome_time / 1000000) - 11644473600
        return datetime.fromtimestamp(unix_timestamp)
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def truncate_string(s, max_length=500):
    """截断过长的字符串"""
    if s and len(s) > max_length:
        return s[:max_length] + "..."
    return s


def find_profile_dir(profile_path):
    """查找可用的浏览器 profile 目录"""
    for name in ["Default", "Profile 1", "Profile 2", "Profile 3"]:
        candidate = os.path.join(profile_path, name)
        if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "History")):
            return candidate
    return None


def get_chromium_history(db_path):
    """获取 Chrome/Edge 历史记录"""
    temp_file = None
    conn = None

    try:
        with tempfile.NamedTemporaryFile(prefix="browser_history_", suffix=".db", delete=False) as tf:
            temp_file = tf.name

        shutil.copy2(db_path, temp_file)

        conn = sqlite3.connect(temp_file)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT url, title, last_visit_time, visit_count
            FROM urls
            ORDER BY last_visit_time DESC
        """)

        history = []
        for url, title, last_visit_time, visit_count in cursor.fetchall():
            visit_time = chrome_time_to_datetime(last_visit_time)
            history.append({
                "title": truncate_string(title, 500),
                "url": truncate_string(url, 500),
                "time": visit_time.isoformat(timespec="seconds") if visit_time else None,
                "visits": visit_count
            })

        cursor.close()
        return history

    except Exception as exc:
        return {"error": f"Failed to read browser history: {exc}"}

    finally:
        if conn:
            conn.close()
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass


def extract_history(browser="chrome"):
    """
    提取浏览器历史记录

    Args:
        browser: 浏览器类型，'chrome' 或 'edge'

    Returns:
        list: 历史记录列表
    """
    browser = (browser or "chrome").lower()
    if browser not in ("chrome", "edge"):
        return {"error": f"Unsupported browser: {browser}"}

    profile_path = get_browser_data_dir(browser)
    if not profile_path or not os.path.isdir(profile_path):
        return {"error": f"Browser not found: {browser}"}

    profile_dir = find_profile_dir(profile_path)
    if not profile_dir:
        return {"error": "History file not found"}

    history_path = os.path.join(profile_dir, "History")
    return get_chromium_history(history_path)


try:
    browser = kwargs.get("browser", "chrome")
    result = extract_history(browser)
    print(json.dumps(result, indent=2, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False))
