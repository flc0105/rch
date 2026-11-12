SCRIPT_METADATA = {
    "name": "common/file/hexdump",
    "display_name": "Hex Dump",
    "description": "Display a hex dump of a file's contents for quick inspection",
    "platforms": ["common"],
    "category": "File",
    "params": [
        {
            "name": "path",
            "label": "File",
            "type": "remote_file",
            "required": True,
            "description": "Choose a file to inspect."
        }
    ]
}

import os
import sys


def printable(bs):
    out = ""
    for b in bs:
        if 32 <= b <= 126:
            out += chr(b)
        else:
            out += "."
    return out


def hexdump(path, limit=4096, width=16):
    with open(path, "rb") as f:
        data = f.read(limit)

    print("file:", path)
    print("size:", os.path.getsize(path), "bytes")
    print()

    for offset in range(0, len(data), width):
        chunk = data[offset:offset + width]
        hx = " ".join("{:02x}".format(b) for b in chunk)
        hx = hx.ljust(width * 3 - 1)
        asc = printable(chunk)
        print("{:08x}  {}  |{}|".format(offset, hx, asc))


if __name__ == "__main__":
    path = kwargs.get('path')
    hexdump(path)