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

BREW = "brew"


def run_brew_info():
    result = subprocess.run(
        [BREW, "info", "--json=v2", "--installed"],
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        print(json.dumps([{
            "type": "",
            "token": "",
            "name": "",
            "tap": "",
            "installed_ver": "",
            "desc": "",
            "homepage": "",
            "url": "",
            "depends_on": [],
            "installed_time": "",
            "error": result.stderr.strip() or result.stdout.strip()
        }], ensure_ascii=False, indent=2))
        raise SystemExit(1)

    return json.loads(result.stdout)


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


def main():
    data = run_brew_info()

    output = []

    for formula in data.get("formulae") or []:
        output.append(normalize_formula(formula))

    for cask in data.get("casks") or []:
        output.append(normalize_cask(cask))

    output.sort(key=lambda x: (x["type"], x["token"]))

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()