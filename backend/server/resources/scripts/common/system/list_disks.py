SCRIPT_METADATA = {
    "name": "common/system/list_disks",
    "display_name": "List Disks",
    "description": "List mounted disks and storage usage",
    "platforms": ["common"],
    "category": "System",
    "params": []
}

import json
import psutil


def get_readable_size(size_bytes: int) -> str:
    if size_bytes is None:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(size_bytes)

    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024


result = []
seen = set()

try:
    for partition in psutil.disk_partitions():
        unique_key = (partition.device, partition.mountpoint)
        if unique_key in seen:
            continue
        seen.add(unique_key)

        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except (PermissionError, OSError):
            continue

        result.append({
            "mount_point": partition.mountpoint or "",
            "device": partition.device or "",
            "file_system": partition.fstype or "N/A",
            "total_size": get_readable_size(usage.total),
            "used": get_readable_size(usage.used),
            "free": get_readable_size(usage.free),
            "percentage": float(usage.percent)
        })

    result.sort(key=lambda x: (x["mount_point"] or "").lower())
    print(json.dumps(result, ensure_ascii=False, indent=2))

except Exception as e:
    print(json.dumps({"error": str(e)}, ensure_ascii=False))