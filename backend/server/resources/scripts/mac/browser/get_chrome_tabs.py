SCRIPT_METADATA = {
    "name": "mac/browser/get_chrome_tabs",
    "display_name": "Chrome Tabs",
    "description": "List open Chrome tabs.",
    "platforms": ["mac"],
    "category": "Browser",
    "params": []
}

import json
import subprocess


def is_chrome_running():
    script = '''
    tell application "System Events"
        return (exists process "Google Chrome")
    end tell
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True
    )
    return "true" in result.stdout.lower()


def get_chrome_tabs():
    if not is_chrome_running():
        return {"error": "Chrome is not running."}

    script = r'''
    tell application "Google Chrome"
        set outputText to ""
        set windowCount to count of windows

        repeat with i from 1 to windowCount
            set currentWindow to window i
            set tabCount to count of tabs of currentWindow

            repeat with j from 1 to tabCount
                set currentTab to tab j of currentWindow
                set tabTitle to title of currentTab
                set tabURL to URL of currentTab

                set outputText to outputText & (tabTitle as string) & "|||" & (tabURL as string) & "|||" & (i as string) & linefeed
            end repeat
        end repeat

        return outputText
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            return {"error": (result.stderr or "Failed to retrieve Chrome tabs.").strip()}

        tabs = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or "|||" not in line:
                continue

            parts = line.split("|||")
            if len(parts) != 3:
                continue

            title, url, window_index = [p.strip() for p in parts]

            if not title:
                continue
            if url.startswith("chrome://") or url.startswith("chrome-extension://"):
                continue
            if title == "新标签页":
                continue

            tabs.append({
                "title": title,
                "url": url,
                "window": int(window_index) if window_index.isdigit() else 0
            })

        return tabs

    except subprocess.TimeoutExpired:
        return {"error": "Timed out while retrieving Chrome tabs."}
    except Exception as exc:
        return {"error": str(exc)}


try:
    print(json.dumps(get_chrome_tabs(), indent=2, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False))
