SCRIPT_METADATA = {
    "name": "mac/software/get_brew_packages",
    "display_name": "Homebrew Packages",
    "description": "List all installed Homebrew formulae and casks",
    "platforms": ["mac"],
    "category": "Software",
    "params": []
}

import json
import subprocess
import datetime as dt
import os
import shutil
import sys
from pathlib import Path

BREW = "brew"
COMMAND_TIMEOUT_SECONDS = 60


def find_brew():
    found = shutil.which(BREW)
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def run_brew_info():
    brew = find_brew()
    if not brew:
        return None, ["Homebrew executable not found"]

    try:
        result = subprocess.run(
            [brew, "info", "--json=v2", "--installed"],
            text=True,
            capture_output=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return None, [f"Homebrew inventory timed out after {COMMAND_TIMEOUT_SECONDS}s"]
    except OSError as exc:
        return None, [f"Cannot run Homebrew: {exc}"]

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return None, [f"Homebrew inventory failed ({result.returncode}): {detail or 'no error details'}"]

    warnings = [line.strip() for line in result.stderr.splitlines() if line.strip()]
    try:
        data = json.loads(result.stdout)
    except ValueError as exc:
        return None, [f"Cannot parse Homebrew JSON: {exc}"]
    if not isinstance(data, dict) or any(
        not isinstance(data.get(key), list) for key in ("formulae", "casks")
    ):
        return None, ["Unexpected Homebrew JSON structure"]
    return data, warnings


def format_time(value):
    if value in (None, "", 0, "0"):
        return ""

    try:
        return dt.datetime.fromtimestamp(int(value)).isoformat(timespec="seconds")
    except Exception:
        return ""


def list_to_string(value):
    if value is None:
        return ""

    if isinstance(value, list):
        return ", ".join(str(x) for x in value if x is not None)

    return str(value)


def formula_installed_version(formula):
    installed = formula.get("installed") or []

    versions = []
    for item in installed:
        if isinstance(item, dict):
            version = item.get("version")
            if version:
                versions.append(str(version))

    return ", ".join(versions)


def formula_installed_time(formula):
    installed = formula.get("installed") or []

    times = []
    for item in installed:
        if isinstance(item, dict):
            value = (
                item.get("installed_time")
                or item.get("time")
            )
            formatted = format_time(value)
            if formatted:
                times.append(formatted)

    return ", ".join(times)


def formula_url(formula):
    urls = formula.get("urls") or {}

    stable = urls.get("stable")
    if isinstance(stable, dict):
        return stable.get("url") or ""

    head = urls.get("head")
    if isinstance(head, dict):
        return head.get("url") or ""

    return ""


def normalize_formula(formula):
    return {
        "type": "formula",
        "token": formula.get("name") or "",
        "name": formula.get("full_name") or formula.get("name") or "",
        "tap": formula.get("tap") or "",
        "installed_ver": formula_installed_version(formula),
        "desc": formula.get("desc") or "",
        "homepage": formula.get("homepage") or "",
        "url": formula_url(formula),
        "depends_on": formula.get("dependencies") or [],
        "installed_time": formula_installed_time(formula),
    }


def cask_installed_version(cask):
    installed = cask.get("installed")

    if isinstance(installed, list):
        return ", ".join(str(x) for x in installed if x is not None)

    if installed:
        return str(installed)

    return cask.get("version") or ""


def normalize_cask_depends_on(cask):
    depends_on = cask.get("depends_on") or {}
    output = []

    if not isinstance(depends_on, dict):
        return output

    for key, value in depends_on.items():
        if isinstance(value, dict):
            for op, vals in value.items():
                if isinstance(vals, list):
                    for v in vals:
                        output.append(f"{key} {op} {v}")
                else:
                    output.append(f"{key} {op} {vals}")
        elif isinstance(value, list):
            for v in value:
                output.append(f"{key}: {v}")
        elif value:
            output.append(f"{key}: {value}")

    return output


def normalize_cask(cask):
    return {
        "type": "cask",
        "token": cask.get("token") or "",
        "name": list_to_string(cask.get("name")),
        "tap": cask.get("tap") or "",
        "installed_ver": cask_installed_version(cask),
        "desc": cask.get("desc") or "",
        "homepage": cask.get("homepage") or "",
        "url": cask.get("url") or "",
        "depends_on": normalize_cask_depends_on(cask),
        "installed_time": format_time(cask.get("installed_time")),
    }


def collect():
    data, warnings = run_brew_info()
    if data is None:
        return None, warnings

    try:
        output = []
        for formula in data["formulae"]:
            output.append(normalize_formula(formula))
        for cask in data["casks"]:
            output.append(normalize_cask(cask))
        output.sort(key=lambda x: (x["type"], x["token"]))
    except (TypeError, AttributeError, KeyError, ValueError) as exc:
        return None, [f"Cannot process Homebrew inventory: {exc}"]
    return output, warnings


def main():
    rows, warnings = collect()
    for warning in warnings:
        level = "ERROR" if rows is None else "WARNING"
        print(f"[BREW] {level}: {warning}", file=sys.stderr, flush=True)
    if rows is None:
        raise SystemExit(1)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()