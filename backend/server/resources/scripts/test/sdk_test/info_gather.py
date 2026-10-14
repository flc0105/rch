SCRIPT_METADATA = {
    "display_name": "Machine Info Collection Report",
    "description": "收集当前 client 的 context、system paths、pinned paths、getinfo、artifacts、keychains，并生成 markdown 报告。",
    "params": [],
    "api_grants": [
        "artifacts:list",
        "keychains:list",
        "workspace:read",
    ]
}

import os
import tempfile
import time

from client.runtime.sdk import artifact, command, context, keychains, workspace


def md(value):
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(md(value) for value in row) + " |")
    return "\n".join(lines)


def human_size(value):
    try:
        size = float(value or 0)
    except Exception:
        return str(value or "")

    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size = size / 1024
        index += 1

    if index == 0:
        return f"{int(size)} {units[index]}"
    return f"{size:.2f} {units[index]}"


def machine_short_id():
    value = context.machine_id() or context.client_id() or "unknown"
    return value[:12]


def section(lines, title):
    lines.append("")
    lines.append(f"## {title}")
    lines.append("")


def get_output_data(result):
    output = getattr(result, "output", None)

    if isinstance(output, dict):
        return output

    data = getattr(output, "data", None)
    if isinstance(data, dict):
        return data

    if isinstance(result, dict):
        data = result.get("data")
        if isinstance(data, dict):
            return data

    return {}


def get_artifact_type(item):
    return item.get("artifact_type") or item.get("type") or ""


def get_artifact_filename(item):
    return item.get("original_name") or item.get("stored_name") or item.get("filename") or ""


def get_artifact_category(item):
    return item.get("category") or ""


def artifact_sort_key(item):
    artifact_type = get_artifact_type(item)
    type_order = {
        "files": 0,
        "server_files": 1,
        "previews": 2,
        "command_output": 3,
    }
    return (
        type_order.get(artifact_type, 99),
        artifact_type,
        get_artifact_filename(item),
        item.get("created_at") or "",
    )


def collect_context_rows():
    return [
        ["client_id", context.client_id()],
        ["command_id", context.command_id()],
        ["hostname", context.hostname()],
        ["machine_id", context.machine_id()],
        ["script_name", context.script_name()],
        ["arch", context.arch()],
        ["os_type", context.os_type()],
        ["os_alias", context.os_alias()],
        ["os_ver", context.os_ver()],
    ]


def collect_system_path_rows():
    paths = workspace.system_paths()
    return [[key, paths.get(key)] for key in sorted(paths.keys())]


def collect_pinned_path_rows():
    paths = workspace.as_dict()
    return [[key, paths.get(key)] for key in sorted(paths.keys())]


def collect_getinfo_rows():
    result = command.run_client("getinfo")
    data = get_output_data(result)
    return [[key, data.get(key)] for key in sorted(data.keys())]


def collect_artifact_rows():
    machine_id = context.machine_id()
    if not machine_id:
        return []

    items = artifact.list(machine_id=machine_id)
    items = [item for item in items if isinstance(item, dict)]

    rows = []
    for item in sorted(items, key=artifact_sort_key):
        rows.append([
            get_artifact_type(item),
            get_artifact_category(item),
            get_artifact_filename(item),
            item.get("artifact_id") or "",
            human_size(item.get("size")),
            item.get("created_at") or "",
        ])
    return rows


def collect_keychain_rows():
    items = keychains.list()
    items = [item for item in items if isinstance(item, dict)]
    items = sorted(items, key=lambda item: (
        item.get("kind") or "",
        item.get("name") or "",
        item.get("created_at") or "",
    ))

    rows = []
    for item in items:
        rows.append([
            item.get("kind") or "",
            item.get("name") or "",
            item.get("username") or "",
            item.get("site") or "",
            item.get("created_at") or "",
            item.get("updated_at") or "",
        ])
    return rows


def build_report():
    report_id = machine_short_id()
    lines = []

    lines.append(f"# {report_id}_report")
    lines.append("")
    lines.append(f"- generated_at: `{time.strftime('%Y-%m-%d %H:%M:%S')}`")
    lines.append(f"- machine_short_id: `{report_id}`")

    section(lines, "Context")
    lines.append(table(
        ["Key", "Value"],
        collect_context_rows(),
    ))

    section(lines, "System Paths")
    system_path_rows = collect_system_path_rows()
    lines.append(table(["Name", "Path"], system_path_rows) if system_path_rows else "_No system paths found._")

    section(lines, "Pinned Paths")
    pinned_path_rows = collect_pinned_path_rows()
    lines.append(table(["Name", "Path"], pinned_path_rows) if pinned_path_rows else "_No pinned paths found._")

    section(lines, "GetInfo")
    getinfo_rows = collect_getinfo_rows()
    lines.append(table(["Key", "Value"], getinfo_rows) if getinfo_rows else "_No getinfo data found._")

    section(lines, "Artifacts")
    artifact_rows = collect_artifact_rows()
    lines.append(table(
        ["Type", "Category", "Filename", "Artifact ID", "Size", "Created At"],
        artifact_rows,
    ) if artifact_rows else "_No artifacts found._")

    section(lines, "Keychains")
    keychain_rows = collect_keychain_rows()
    lines.append(table(
        ["Kind", "Name", "Username", "Site", "Created At", "Updated At"],
        keychain_rows,
    ) if keychain_rows else "_No keychains found._")

    return "\n".join(lines) + "\n"


def main():
    report_name = f"{machine_short_id()}_report.md"
    report_dir = tempfile.mkdtemp(prefix="script_sdk_report_")
    report_path = os.path.join(report_dir, report_name)

    report = build_report()

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print("report_name =", report_name)
    print("report_path =", report_path)
    print("")
    print(report)

    saved = artifact.save(
        report_path,
        type="server_files",
        category="script_sdk_report",
        extra={
            "kind": "machine_info_report",
            "machine_short_id": machine_short_id(),
            "machine_id": context.machine_id(),
            "client_id": context.client_id(),
        },
    )

    print("")
    print("saved_report_artifact =", saved)
    print("PASS")


if __name__ == "__main__":
    main()