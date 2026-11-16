# server/scripts/jobs/duplicate_file_finder.py
# Find duplicate files recursively and output beautified JSON array

JOB_METADATA = {
    "name": "duplicate_file_finder",
    "display_name": "Duplicate File Finder",
    "description": "Recursively scan a directory and list duplicate files by file content hash",
    "platforms": ["darwin", "windows", "linux"],
    "params": [
        {
            "name": "scan_path",
            "type": "string",
            "required": False,
            "default": ".",
            "description": "Directory path to scan recursively. Defaults to current directory."
        }
    ]
}

import hashlib
import json
import os
import time
from collections import defaultdict

from client.jobs.job import Job


class DuplicateFileFinder(Job):
    HASH_CHUNK_SIZE = 1024 * 1024

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

    def scan_files_by_size(self):
        files_by_size = defaultdict(list)
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

                            # 空文件重复价值较低，先跳过，避免结果噪声过多。
                            if file_size <= 0:
                                continue

                            files_by_size[file_size].append({
                                "file_name": entry.name,
                                "file_path": os.path.abspath(entry.path),
                                "_size_bytes": file_size
                            })

                        except (PermissionError, FileNotFoundError, OSError):
                            continue

            except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
                continue

        return files_by_size

    def calculate_file_hash(self, file_path):
        hash_obj = hashlib.sha256()

        try:
            with open(file_path, "rb") as file:
                while not self.stop_event.is_set():
                    chunk = file.read(self.HASH_CHUNK_SIZE)
                    if not chunk:
                        break
                    hash_obj.update(chunk)

            if self.stop_event.is_set():
                return None

            return hash_obj.hexdigest()

        except (PermissionError, FileNotFoundError, IsADirectoryError, OSError):
            return None

    def find_duplicate_files(self):
        duplicate_groups = []
        files_by_size = self.scan_files_by_size()

        for file_size, files in files_by_size.items():
            if self.stop_event.is_set():
                break

            if len(files) < 2:
                continue

            files_by_hash = defaultdict(list)

            for file_info in files:
                if self.stop_event.is_set():
                    break

                file_hash = self.calculate_file_hash(file_info["file_path"])
                if not file_hash:
                    continue

                files_by_hash[file_hash].append(file_info)

            for file_hash, matched_files in files_by_hash.items():
                if len(matched_files) < 2:
                    continue

                matched_files.sort(key=lambda item: item["file_path"])

                for item in matched_files:
                    item.pop("_size_bytes", None)

                duplicate_groups.append({
                    "_size_bytes": file_size,
                    "_wasted_bytes": file_size * (len(matched_files) - 1),
                    "file_hash": file_hash,
                    "file_size": self.human_readable_size(file_size),
                    "duplicate_count": len(matched_files),
                    "wasted_size": self.human_readable_size(file_size * (len(matched_files) - 1)),
                    "files": matched_files
                })

        duplicate_groups.sort(
            key=lambda item: (item["_wasted_bytes"], item["_size_bytes"], item["duplicate_count"]),
            reverse=True
        )

        for item in duplicate_groups:
            item.pop("_size_bytes", None)
            item.pop("_wasted_bytes", None)

        return duplicate_groups

    def run(self):
        self.mark_running()
        self.send_to_server(1, f"Duplicate file scan started: {self.scan_path}")
        self.send_to_server(1, "Scanning recursively for duplicate files by size and SHA-256 hash...")

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

            duplicate_files = self.find_duplicate_files()
            elapsed_seconds = time.time() - started_at

            if self.stop_event.is_set():
                self.send_to_server(
                    1,
                    f"Duplicate file scan cancelled. Partial results collected in {elapsed_seconds:.2f}s."
                )
            else:
                self.send_to_server(
                    1,
                    f"Duplicate file scan completed in {elapsed_seconds:.2f}s. Found {len(duplicate_files)} duplicate group(s)."
                )

            output_json = json.dumps(
                duplicate_files,
                ensure_ascii=False,
                indent=2
            )

            self.send_to_server(1, output_json)

        finally:
            self.mark_stopped()

    def stop(self, notify=True):
        self.request_stop(notify=notify)