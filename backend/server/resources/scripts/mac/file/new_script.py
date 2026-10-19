
SCRIPT_METADATA = {
    "name": "mac/debug/trash_access",
    "display_name": "Trash Access Check",
    "description": "Diagnose macOS Trash access and volume detection.",
    "category": "file",
    "tags": ["macos", "trash", "diagnostics"],
    "platforms": ["mac"],
    "params": [],
}

import os
import sys
from pathlib import Path

uid = os.getuid()
print("UID:", uid, "Python:", sys.executable)

for directory in (
    "/Volumes",
    "/Volumes/T7",
    f"/Volumes/T7/.Trashes/{uid}",
    str(Path.home() / ".Trash"),
):
    print("\nPATH", directory)
    print("is_dir:", os.path.isdir(directory),
          "is_mount:", os.path.ismount(directory))
    try:
        with os.scandir(directory) as entries:
            first = next(entries, None)
        print("scandir: OK; first entry:",
              first.name if first else "(empty)")
    except OSError as exc:
        print("scandir: ERROR", type(exc).__name__, str(exc))

try:
    with os.scandir("/Volumes") as volumes:
        for volume in volumes:
            if volume.name == "T7":
                print("\nT7 discovered:", volume.path)
                print("entry.is_dir(no-follow):",
                      volume.is_dir(follow_symlinks=False))
                print("os.path.ismount:",
                      os.path.ismount(volume.path))
except OSError as exc:
    print("volume discovery ERROR:", repr(exc))