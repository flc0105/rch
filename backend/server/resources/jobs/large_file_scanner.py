# server/scripts/jobs/large_file_scanner.py
# Scan large files recursively and output beautified JSON array

JOB_METADATA = {
    "name": "large_file_scanner",
    "display_name": "Large File Scanner",
    "description": "Recursively scan a directory and list files larger than 100MB",
    "platforms": ["darwin", "windows", "linux"],
    "params": [
        {
            "name": "scan_path",
            "type": "remote_folder",
            # "type": "string",
            "required": False,
            "default": ".",
            "description": "Directory path to scan recursively. Defaults to current directory."
        }
    ]
}

import json
import os
import time

from client.jobs.job import Job


class LargeFileScanner(Job):
    LARGE_FILE_THRESHOLD_BYTES = 100 * 1024 * 1024

    def __init__(self):
        super().__init__()
        self.scan_path = "."

    def on_context_bound(self):
        self.scan_path = self.get_job_param("scan_path", ".") or "."
        self.scan_path = os.path.abspath(os.path.expanduser(self.scan_path))

    def human_readable_size(self, size_bytes):
        units = ["B", "KB", "MB", "GB", "TB", "PB"]
        size = float(size_bytes)

        for unit in units:
            if size < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(size)} {unit}"
                return f"{size:.2f} {unit}"
            size /= 1024

    def scan_large_files(self):
        large_files = []
        stack = [self.scan_path]

        while stack and not self.stop_event.is_set():
            current_path = stack.pop()

            try:
                with os.scandir(current_path) as entries:
                    for entry in entries:
                        if self.stop_event.is_set():
                            break

                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                                continue

                            if not entry.is_file(follow_symlinks=False):
                                continue

                            stat_result = entry.stat(follow_symlinks=False)
                            file_size = stat_result.st_size

                            if file_size > self.LARGE_FILE_THRESHOLD_BYTES:
                                large_files.append({
                                    "_size_bytes": file_size,
                                    "file_name": entry.name,
                                    "file_path": os.path.abspath(entry.path),
                                    "file_size": self.human_readable_size(file_size)
                                })

                        except (PermissionError, FileNotFoundError, OSError):
                            continue

            except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
                continue

        large_files.sort(key=lambda item: item["_size_bytes"], reverse=True)

        for item in large_files:
            item.pop("_size_bytes", None)

        return large_files

    def run(self):
        self.mark_running()
        self.send_to_server(1, f"Large file scan started: {self.scan_path}")
        self.send_to_server(1, "Scanning recursively for files larger than 100MB...")

        started_at = time.time()

        try:
            if not os.path.exists(self.scan_path):
                self.send_to_server(1, f"Scan path does not exist: {self.scan_path}")
                self.send_to_server(1, "[]")
                return

            if not os.path.isdir(self.scan_path):
                self.send_to_server(1, f"Scan path is not a directory: {self.scan_path}")
                self.send_to_server(1, "[]")
                return

            large_files = self.scan_large_files()
            elapsed_seconds = time.time() - started_at

            if self.stop_event.is_set():
                self.send_to_server(
                    1,
                    f"Large file scan cancelled. Partial results collected in {elapsed_seconds:.2f}s."
                )
            else:
                self.send_to_server(
                    1,
                    f"Large file scan completed in {elapsed_seconds:.2f}s. Found {len(large_files)} large file(s)."
                )

            output_json = json.dumps(
                large_files,
                ensure_ascii=False,
                indent=2
            )

            self.send_to_server(1, output_json)

        finally:
            self.mark_stopped()

    def stop(self, notify=True):
        self.request_stop(notify=notify)