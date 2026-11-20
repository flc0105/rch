#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "common/browser/get_chrome_extensions",
    "display_name": "Chrome Extensions",
    "description": "List installed Chrome extensions across local profiles.",
    "platforms": ["mac", "win"],
    "category": "Browser",
    "params": [],
}

import json
import os
import re
from pathlib import Path

from client.runtime.sdk import context


MESSAGE_REFERENCE = re.compile(r"^__MSG_([A-Za-z0-9_]+)__$", re.IGNORECASE)


def chrome_data_dir(os_alias):
    if os_alias == "mac":
        return Path.home() / "Library/Application Support/Google/Chrome"
    if os_alias == "win":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData/Local"
        return base / "Google/Chrome/User Data"
    raise RuntimeError(f"Unsupported platform: {os_alias}")


def read_json(path):
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def extension_settings(profile):
    settings = {}
    for filename in ("Preferences", "Secure Preferences"):
        path = profile / filename
        if not path.is_file():
            continue
        content = read_json(path)
        found = content.get("extensions", {}).get("settings", {})
        if isinstance(found, dict):
            for extension_id, details in found.items():
                if isinstance(details, dict):
                    settings.setdefault(extension_id, {}).update(details)
    return settings


def extension_enabled(details):
    # New Chrome versions record disabling reasons instead of "state".
    # An absent disable_reasons key means there are no disable reasons.
    reasons = details.get("disable_reasons")
    if isinstance(reasons, list):
        return len(reasons) == 0
    if "disable_reasons" in details:
        return None

    state = details.get("state")
    if state in (0, 1):
        return state == 1
    if state is not None:
        return None
    return True


def extension_folder(profile, extension_id, version):
    root = profile / "Extensions" / extension_id
    if not root.is_dir():
        return None
    for folder in sorted(root.iterdir()):
        if folder.is_dir() and folder.name.split("_", 1)[0] == str(version):
            return folder
    return None


def resolve_message(value, folder, default_locale):
    if not isinstance(value, str):
        return None
    match = MESSAGE_REFERENCE.fullmatch(value)
    if not match or folder is None:
        return value
    locales_root = folder / "_locales"
    if not locales_root.is_dir():
        return value

    candidates = [default_locale, "en", "en_US"]
    candidates.extend(p.name for p in locales_root.iterdir() if p.is_dir())
    seen = set()
    for locale in candidates:
        if not locale or locale in seen:
            continue
        seen.add(locale)
        path = locales_root / locale / "messages.json"
        if not path.is_file():
            continue
        try:
            messages = read_json(path)
        except (OSError, ValueError):
            continue
        for key, item in messages.items():
            if key.casefold() == match.group(1).casefold() and isinstance(item, dict):
                message = item.get("message")
                if isinstance(message, str):
                    return message
    return value


def scan_extensions(os_alias):
    root = chrome_data_dir(os_alias)
    if not root.is_dir():
        raise FileNotFoundError("Google Chrome user data directory not found.")

    result = []
    for profile in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        if not profile.is_dir():
            continue
        if not (profile / "Preferences").is_file() and not (profile / "Secure Preferences").is_file():
            continue

        for extension_id, details in extension_settings(profile).items():
            if details.get("state") == 2:
                continue
            manifest = details.get("manifest")
            if not isinstance(manifest, dict) or "app" in manifest:
                continue

            version = manifest.get("version")
            folder = extension_folder(profile, extension_id, version)
            default_locale = manifest.get("default_locale")
            result.append({
                "profile": profile.name,
                "id": extension_id,
                "name": resolve_message(manifest.get("name"), folder, default_locale),
                "version": version,
                "enabled": extension_enabled(details),
                "description": resolve_message(manifest.get("description"), folder, default_locale),
            })

    return sorted(result, key=lambda item: (
        item["profile"].casefold(), (item["name"] or "").casefold(), item["id"]
    ))


def main():
    try:
        output = scan_extensions(context.os_alias())
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
        output = {"error": f"Failed to list Chrome extensions: {exc}"}
    context.emit(output)


if __name__ == "__main__":
    main()