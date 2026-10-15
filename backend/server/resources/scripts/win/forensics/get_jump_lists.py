SCRIPT_METADATA = {
    "name": "win/forensics/get_jump_lists",
    "display_name": "Jump Lists",
    "description": "Retrieve Windows Jump List activity from local user profiles.",
    "platforms": ["win"],
    "category": "Forensics",
    "params": []
}

import os
import json
import struct
from pathlib import Path
from datetime import datetime, timezone, timedelta


LNK_SIGNATURE = b"\x4c\x00\x00\x00\x01\x14\x02\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00\x46"

APP_ID_MAP = {
    "1b4dd67f29cb1962": "Windows Explorer",
    "5f7b5f1e01b83767": "Microsoft Office",
    "9b9cdc69c1c24e2b": "Microsoft Word",
    "9839aec31243a928": "Microsoft Excel",
    "f5ac5390b9115fdb": "Microsoft PowerPoint",
    "d249d9ddd424b688": "Microsoft Access",
    "a7bd71699cd38d1c": "Notepad",
    "918e0ecb43d17e23": "Notepad++",
    "590aee7bdd69b59b": "Microsoft Edge",
    "28c8b86deab549a1": "Google Chrome",
    "b74736c2bd8cc8a5": "Mozilla Firefox",
}


def filetime_to_string(value):
    try:
        if not value:
            return ""

        base = datetime(1601, 1, 1, tzinfo=timezone.utc)
        dt = base + timedelta(microseconds=value / 10)

        if dt.year < 1980 or dt.year > 2100:
            return ""

        return dt.astimezone().isoformat(timespec="seconds")
    except Exception:
        return ""


def timestamp_to_string(ts):
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.astimezone().isoformat(timespec="seconds")
    except Exception:
        return ""


def read_c_string(data, offset, is_unicode=False):
    try:
        if offset <= 0 or offset >= len(data):
            return ""

        if is_unicode:
            end = offset
            while end + 1 < len(data):
                if data[end:end + 2] == b"\x00\x00":
                    break
                end += 2
            return data[offset:end].decode("utf-16le", errors="ignore").strip("\x00").strip()

        end = data.find(b"\x00", offset)
        if end == -1:
            end = len(data)

        try:
            return data[offset:end].decode("mbcs", errors="ignore").strip()
        except Exception:
            return data[offset:end].decode("latin-1", errors="ignore").strip()
    except Exception:
        return ""


def read_counted_string(data, offset, is_unicode):
    try:
        if offset + 2 > len(data):
            return "", offset

        length = struct.unpack_from("<H", data, offset)[0]
        offset += 2

        if is_unicode:
            byte_len = length * 2
            raw = data[offset:offset + byte_len]
            text = raw.decode("utf-16le", errors="ignore")
            offset += byte_len
        else:
            byte_len = length
            raw = data[offset:offset + byte_len]
            try:
                text = raw.decode("mbcs", errors="ignore")
            except Exception:
                text = raw.decode("latin-1", errors="ignore")
            offset += byte_len

        return text.strip("\x00").strip(), offset
    except Exception:
        return "", offset


def parse_lnk(data):
    item = {
        "target_path": "",
        "target_name": "",
        "arguments": "",
        "working_directory": "",
        "icon_location": "",
        "description": "",
        "relative_path": "",
        "drive_type": "",
        "drive_serial_number": "",
        "volume_label": "",
        "local_base_path": "",
        "common_path_suffix": "",
        "file_size": "",
        "file_attributes": "",
        "creation_time": "",
        "access_time": "",
        "write_time": ""
    }

    try:
        if len(data) < 0x4C:
            return item

        if data[:20] != LNK_SIGNATURE:
            return item

        link_flags = struct.unpack_from("<I", data, 0x14)[0]
        file_attributes = struct.unpack_from("<I", data, 0x18)[0]

        item["file_attributes"] = file_attributes
        item["creation_time"] = filetime_to_string(struct.unpack_from("<Q", data, 0x1C)[0])
        item["access_time"] = filetime_to_string(struct.unpack_from("<Q", data, 0x24)[0])
        item["write_time"] = filetime_to_string(struct.unpack_from("<Q", data, 0x2C)[0])
        item["file_size"] = struct.unpack_from("<I", data, 0x34)[0]

        offset = 0x4C

        has_link_target_id_list = bool(link_flags & 0x00000001)
        has_link_info = bool(link_flags & 0x00000002)
        has_name = bool(link_flags & 0x00000004)
        has_relative_path = bool(link_flags & 0x00000008)
        has_working_dir = bool(link_flags & 0x00000010)
        has_arguments = bool(link_flags & 0x00000020)
        has_icon_location = bool(link_flags & 0x00000040)
        is_unicode = bool(link_flags & 0x00000080)

        if has_link_target_id_list:
            if offset + 2 <= len(data):
                id_list_size = struct.unpack_from("<H", data, offset)[0]
                offset += 2 + id_list_size

        if has_link_info and offset + 4 <= len(data):
            link_info_start = offset
            link_info_size = struct.unpack_from("<I", data, offset)[0]

            if link_info_size > 0 and link_info_start + link_info_size <= len(data):
                link_info = data[link_info_start:link_info_start + link_info_size]

                if len(link_info) >= 0x1C:
                    header_size = struct.unpack_from("<I", link_info, 0x04)[0]
                    volume_id_offset = struct.unpack_from("<I", link_info, 0x0C)[0]
                    local_base_path_offset = struct.unpack_from("<I", link_info, 0x10)[0]
                    common_path_suffix_offset = struct.unpack_from("<I", link_info, 0x18)[0]

                    local_base_path_offset_unicode = 0
                    common_path_suffix_offset_unicode = 0

                    if header_size >= 0x24 and len(link_info) >= 0x24:
                        local_base_path_offset_unicode = struct.unpack_from("<I", link_info, 0x1C)[0]
                        common_path_suffix_offset_unicode = struct.unpack_from("<I", link_info, 0x20)[0]

                    if local_base_path_offset_unicode:
                        item["local_base_path"] = read_c_string(link_info, local_base_path_offset_unicode, True)
                    elif local_base_path_offset:
                        item["local_base_path"] = read_c_string(link_info, local_base_path_offset, False)

                    if common_path_suffix_offset_unicode:
                        item["common_path_suffix"] = read_c_string(link_info, common_path_suffix_offset_unicode, True)
                    elif common_path_suffix_offset:
                        item["common_path_suffix"] = read_c_string(link_info, common_path_suffix_offset, False)

                    if volume_id_offset and volume_id_offset < len(link_info):
                        try:
                            vol = link_info[volume_id_offset:]
                            if len(vol) >= 16:
                                drive_type = struct.unpack_from("<I", vol, 4)[0]
                                drive_serial = struct.unpack_from("<I", vol, 8)[0]
                                volume_label_offset = struct.unpack_from("<I", vol, 12)[0]

                                item["drive_type"] = drive_type
                                item["drive_serial_number"] = "%08X" % drive_serial

                                if volume_label_offset:
                                    item["volume_label"] = read_c_string(vol, volume_label_offset, False)
                        except Exception:
                            pass

            offset += link_info_size

        if has_name:
            item["description"], offset = read_counted_string(data, offset, is_unicode)

        if has_relative_path:
            item["relative_path"], offset = read_counted_string(data, offset, is_unicode)

        if has_working_dir:
            item["working_directory"], offset = read_counted_string(data, offset, is_unicode)

        if has_arguments:
            item["arguments"], offset = read_counted_string(data, offset, is_unicode)

        if has_icon_location:
            item["icon_location"], offset = read_counted_string(data, offset, is_unicode)

        if item["local_base_path"] and item["common_path_suffix"]:
            if item["local_base_path"].lower().endswith(item["common_path_suffix"].lower()):
                item["target_path"] = item["local_base_path"]
            else:
                item["target_path"] = item["local_base_path"].rstrip("\\/") + "\\" + item["common_path_suffix"].lstrip("\\/")
        elif item["local_base_path"]:
            item["target_path"] = item["local_base_path"]
        elif item["relative_path"]:
            item["target_path"] = item["relative_path"]

        if item["target_path"]:
            item["target_name"] = os.path.basename(item["target_path"])

    except Exception:
        pass

    return item


FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE


class CompoundFile:
    def __init__(self, data):
        self.data = data
        self.sector_size = 512
        self.mini_sector_size = 64
        self.fat = []
        self.mini_fat = []
        self.directory = []
        self.root_entry = None
        self.mini_stream = b""

        self._parse()

    def _sector(self, sid):
        start = (sid + 1) * self.sector_size
        end = start + self.sector_size
        if start < 0 or end > len(self.data):
            return b""
        return self.data[start:end]

    def _parse(self):
        if len(self.data) < 512:
            return

        if self.data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            return

        sector_shift = struct.unpack_from("<H", self.data, 0x1E)[0]
        mini_sector_shift = struct.unpack_from("<H", self.data, 0x20)[0]

        self.sector_size = 1 << sector_shift
        self.mini_sector_size = 1 << mini_sector_shift

        num_fat_sectors = struct.unpack_from("<I", self.data, 0x2C)[0]
        first_dir_sector = struct.unpack_from("<I", self.data, 0x30)[0]
        mini_cutoff = struct.unpack_from("<I", self.data, 0x38)[0]
        first_mini_fat_sector = struct.unpack_from("<I", self.data, 0x3C)[0]
        first_difat_sector = struct.unpack_from("<I", self.data, 0x44)[0]
        num_difat_sectors = struct.unpack_from("<I", self.data, 0x48)[0]

        difat = []
        for i in range(109):
            sid = struct.unpack_from("<I", self.data, 0x4C + i * 4)[0]
            if sid not in (FREESECT, ENDOFCHAIN):
                difat.append(sid)

        current = first_difat_sector
        for _ in range(num_difat_sectors):
            if current in (FREESECT, ENDOFCHAIN):
                break

            sector = self._sector(current)
            if not sector:
                break

            count = self.sector_size // 4 - 1
            for i in range(count):
                sid = struct.unpack_from("<I", sector, i * 4)[0]
                if sid not in (FREESECT, ENDOFCHAIN):
                    difat.append(sid)

            current = struct.unpack_from("<I", sector, self.sector_size - 4)[0]

        fat_sectors = difat[:num_fat_sectors]
        fat_bytes = b"".join(self._sector(sid) for sid in fat_sectors)

        self.fat = [
            struct.unpack_from("<I", fat_bytes, i)[0]
            for i in range(0, len(fat_bytes) - 3, 4)
        ]

        dir_bytes = self._read_chain(first_dir_sector)
        self._parse_directory(dir_bytes)

        mini_fat_bytes = self._read_chain(first_mini_fat_sector)
        self.mini_fat = [
            struct.unpack_from("<I", mini_fat_bytes, i)[0]
            for i in range(0, len(mini_fat_bytes) - 3, 4)
        ]

        if self.root_entry:
            self.mini_stream = self._read_chain(self.root_entry.get("start_sector", ENDOFCHAIN))[:self.root_entry.get("size", 0)]

    def _read_chain(self, start_sector):
        if start_sector in (FREESECT, ENDOFCHAIN):
            return b""

        result = []
        current = start_sector
        seen = set()

        while current not in (FREESECT, ENDOFCHAIN):
            if current in seen:
                break
            if current >= len(self.fat):
                break

            seen.add(current)
            result.append(self._sector(current))
            current = self.fat[current]

        return b"".join(result)

    def _read_mini_chain(self, start_sector, size):
        if start_sector in (FREESECT, ENDOFCHAIN):
            return b""

        result = []
        current = start_sector
        seen = set()

        while current not in (FREESECT, ENDOFCHAIN):
            if current in seen:
                break
            if current >= len(self.mini_fat):
                break

            seen.add(current)

            start = current * self.mini_sector_size
            end = start + self.mini_sector_size
            result.append(self.mini_stream[start:end])

            current = self.mini_fat[current]

        return b"".join(result)[:size]

    def _parse_directory(self, dir_bytes):
        for offset in range(0, len(dir_bytes) - 127, 128):
            entry = dir_bytes[offset:offset + 128]

            name_len = struct.unpack_from("<H", entry, 64)[0]
            object_type = entry[66]

            if name_len >= 2:
                name_raw = entry[:name_len - 2]
                name = name_raw.decode("utf-16le", errors="ignore")
            else:
                name = ""

            start_sector = struct.unpack_from("<I", entry, 116)[0]
            size = struct.unpack_from("<Q", entry, 120)[0]

            obj = {
                "name": name,
                "type": object_type,
                "start_sector": start_sector,
                "size": size
            }

            self.directory.append(obj)

            if object_type == 5:
                self.root_entry = obj

    def streams(self):
        rows = []

        for entry in self.directory:
            if entry.get("type") != 2:
                continue

            name = entry.get("name", "")
            size = entry.get("size", 0)
            start_sector = entry.get("start_sector", ENDOFCHAIN)

            if size == 0:
                content = b""
            elif size < 4096 and self.mini_stream:
                content = self._read_mini_chain(start_sector, size)
            else:
                content = self._read_chain(start_sector)[:size]

            rows.append({
                "name": name,
                "data": content
            })

        return rows


def extract_lnk_blobs_from_custom_destination(data):
    offsets = []
    start = 0

    while True:
        pos = data.find(LNK_SIGNATURE, start)
        if pos == -1:
            break
        offsets.append(pos)
        start = pos + 1

    blobs = []

    for i, pos in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < len(offsets) else len(data)
        blobs.append(data[pos:end])

    return blobs


def get_profiles():
    profiles = []
    users_dir = Path(os.environ.get("SystemDrive", "C:") + "\\Users")

    if users_dir.exists():
        for p in users_dir.iterdir():
            if p.is_dir():
                profiles.append(p)

    return profiles


def base_record(profile, jump_list_path, jump_list_type, app_id, entry_index, entry_type):
    return {
        "user_profile": str(profile),
        "path": str(jump_list_path),
        "jump_list_type": jump_list_type,
        "app_id": app_id,
        "app_name": APP_ID_MAP.get(app_id.lower(), ""),
        "entry_index": entry_index,
        "entry_type": entry_type,
        "target_path": "",
        "target_name": "",
        "arguments": "",
        "working_directory": "",
        "icon_location": "",
        "description": "",
        "relative_path": "",
        "drive_type": "",
        "drive_serial_number": "",
        "volume_label": "",
        "local_base_path": "",
        "common_path_suffix": "",
        "file_size": "",
        "file_attributes": "",
        "creation_time": "",
        "access_time": "",
        "write_time": "",
        "source_mtime": timestamp_to_string(os.path.getmtime(jump_list_path)) if os.path.exists(jump_list_path) else ""
    }


result = []

for profile in get_profiles():
    automatic_dir = profile / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Recent" / "AutomaticDestinations"
    custom_dir = profile / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Recent" / "CustomDestinations"

    if automatic_dir.exists():
        for path in automatic_dir.glob("*.automaticDestinations-ms"):
            app_id = path.name.split(".")[0]

            try:
                data = path.read_bytes()
                cf = CompoundFile(data)

                entry_index = 0
                for stream in cf.streams():
                    stream_name = stream.get("name", "")
                    stream_data = stream.get("data", b"")

                    if stream_name.lower() == "destlist":
                        continue

                    if not stream_data.startswith(LNK_SIGNATURE):
                        continue

                    record = base_record(profile, path, "AutomaticDestinations", app_id, entry_index, stream_name)
                    record.update(parse_lnk(stream_data))
                    result.append(record)
                    entry_index += 1

            except Exception:
                pass

    if custom_dir.exists():
        for path in custom_dir.glob("*.customDestinations-ms"):
            app_id = path.name.split(".")[0]

            try:
                data = path.read_bytes()
                blobs = extract_lnk_blobs_from_custom_destination(data)

                for entry_index, blob in enumerate(blobs):
                    record = base_record(profile, path, "CustomDestinations", app_id, entry_index, "lnk")
                    record.update(parse_lnk(blob))
                    result.append(record)

            except Exception:
                pass

output = [
    {
        "user": Path(item["user_profile"]).name,
        "app": item["app_name"] or item["app_id"],
        "source": Path(item["path"]).name,
        "type": "automatic" if item["jump_list_type"] == "AutomaticDestinations" else "custom",
        "target": item["target_path"],
        "arguments": item["arguments"],
        "created": item["creation_time"] or None,
        "accessed": item["access_time"] or None,
        "modified": item["write_time"] or None,
    }
    for item in result
]

print(json.dumps(output, ensure_ascii=False, indent=2))