SCRIPT_METADATA = {
    "name": "common/process/listening_services",
    "display_name": "Listening Services",
    "description": "Explore local listening services and discover web endpoints.",
    "platforms": ["win", "mac", "linux"],
    "category": "Process",
    "params": [
        {
            "name": "mode",
            "label": "Mode",
            "type": "select",
            "options": ["TCP", "HTTP"],
            "required": False,
            "default": "TCP",
            "description": "TCP lists listeners; HTTP identifies local web services."
        }
    ]
}

import concurrent.futures
import html.parser
import http.client
import ipaddress
import json
import ntpath
import os
import re
import shlex
import ssl
import subprocess

import psutil
from client.runtime.sdk import context


HTTP_TIMEOUT = 1.5
MAX_HTML_BYTES = 65536


class TitleParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title and sum(map(len, self.parts)) < 250:
            self.parts.append(data)


def add_listener(rows, port, pid, address, name=None):
    try:
        port = int(port)
    except (TypeError, ValueError):
        return
    if not 0 < port <= 65535:
        return
    key = (port, pid)
    item = rows.setdefault(key, {"port": port, "pid": pid, "addresses": set(), "name": name})
    if address:
        item["addresses"].add(str(address).strip("[]"))
    if name and not item["name"]:
        item["name"] = name


def mac_lsof_listeners():
    """Fallback for macOS where system-wide psutil sockets require root."""
    result = subprocess.run(
        ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpcfn"],
        capture_output=True, text=True, errors="replace", timeout=15, check=False,
    )
    if result.returncode not in (0, 1) and not result.stdout:
        raise RuntimeError(result.stderr.strip() or "lsof failed")
    rows = {}
    pid = name = None
    has_file = False
    for line in result.stdout.splitlines():
        field, value = line[:1], line[1:]
        if field == "p":
            pid = int(value) if value.isdecimal() else None
            name = None
            has_file = False
        elif field == "c":
            name = value
        elif field == "f":
            has_file = True
        elif field == "n" and has_file and pid is not None and ":" in value:
            address, port = value.rsplit(":", 1)
            if port.isdecimal():
                add_listener(rows, port, pid, address, name)
    return list(rows.values())


def listening_sockets(os_alias):
    try:
        connections = psutil.net_connections(kind="tcp")
    except (psutil.AccessDenied, OSError):
        if os_alias == "mac":
            return mac_lsof_listeners()
        raise
    rows = {}
    for conn in connections:
        if conn.status != psutil.CONN_LISTEN or not conn.laddr:
            continue
        address = getattr(conn.laddr, "ip", conn.laddr[0])
        port = getattr(conn.laddr, "port", conn.laddr[1])
        add_listener(rows, port, conn.pid, address)
    return list(rows.values())


def process_value(proc, field):
    try:
        return getattr(proc, field)()
    except (psutil.Error, OSError):
        return None


def resolved_command(argv, exe, cwd, os_alias):
    if not argv:
        return None
    args = list(argv)
    if exe:
        args[0] = exe
    # Match Python Processes: resolve a Python script against its process CWD.
    base = ntpath.basename(argv[0].replace("/", "\\")).lower().removesuffix(".exe")
    if re.fullmatch(r"(?:pythonw?|pypy)(?:\d+(?:\.\d+)*)?", base):
        i = 1
        while i < len(args):
            arg = args[i]
            if arg in ("-m", "-c") or arg.startswith(("-m", "-c")):
                break
            if arg in ("-X", "-W", "--check-hash-based-pycs"):
                i += 2
                continue
            if arg.startswith("-"):
                i += 1
                continue
            paths = ntpath if os_alias == "win" else os.path
            if cwd and paths.isabs(cwd) and not paths.isabs(arg):
                args[i] = paths.normpath(paths.join(cwd, arg))
            break
    return subprocess.list2cmdline(args) if os_alias == "win" else shlex.join(args)


def service_record(listener, os_alias):
    pid = listener["pid"]
    name = listener.get("name")
    user = command = None
    if pid is not None:
        try:
            proc = psutil.Process(pid)
            with proc.oneshot():
                name = process_value(proc, "name") or name
                user = process_value(proc, "username")
                argv = process_value(proc, "cmdline") or []
                exe = process_value(proc, "exe")
                cwd = process_value(proc, "cwd") if argv else None
            command = resolved_command(argv, exe, cwd, os_alias)
        except (psutil.Error, OSError):
            pass
    return {
        "port": listener["port"],
        "pid": pid,
        "user": user,
        "process_name": name,
        "command": command,
    }


def probe_addresses(addresses):
    targets = set()
    for raw in addresses:
        address = raw.strip("[]")
        if address in ("0.0.0.0", "*"):
            targets.add("127.0.0.1")
        elif address == "::":
            targets.add("::1")
        else:
            try:
                if not ipaddress.ip_address(address.split("%", 1)[0]).is_multicast:
                    targets.add(address)
            except ValueError:
                continue
    return sorted(targets, key=lambda a: (a not in ("127.0.0.1", "::1"), a))


def probe_http(address, port, secure):
    connection = None
    try:
        if secure:
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            tls.check_hostname = False
            tls.verify_mode = ssl.CERT_NONE
            connection = http.client.HTTPSConnection(address, port, timeout=HTTP_TIMEOUT, context=tls)
        else:
            connection = http.client.HTTPConnection(address, port, timeout=HTTP_TIMEOUT)
        connection.request("GET", "/", headers={
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.1",
            "Accept-Encoding": "identity",
            "Connection": "close",
            "User-Agent": "RCH-LocalServices",
        })
        response = connection.getresponse()
        title = None
        content_type = response.getheader("Content-Type", "")
        if "html" in content_type.lower():
            body = response.read(MAX_HTML_BYTES)
            match = re.search(r"charset\s*=\s*['\"]?([\w-]+)", content_type, re.I)
            charset = match.group(1) if match else "utf-8"
            try:
                text = body.decode(charset, "replace")
            except LookupError:
                text = body.decode("utf-8", "replace")
            parser = TitleParser()
            parser.feed(text)
            title = " ".join("".join(parser.parts).split())[:250] or None
        scheme = "https" if secure else "http"
        url_host = "[{}]".format(address.replace("%", "%25")) if ":" in address else address
        return {
            "url": "{}://{}:{}/".format(scheme, url_host, port),
            "http_status": response.status,
            "title": title,
            "server_header": response.getheader("Server"),
        }
    except (OSError, ValueError, ssl.SSLError, http.client.HTTPException):
        return None
    finally:
        if connection is not None:
            connection.close()


def detect_web(listener):
    port = listener["port"]
    for addr in probe_addresses(listener["addresses"]):
        schemes = (True, False) if port in (443, 8443, 9443) else (False, True)
        for secure in schemes:
            result = probe_http(addr, port, secure)
            if result is not None:
                return result
    return None


def main():
    os_alias = context.os_alias()
    if os_alias not in ("win", "mac", "linux"):
        raise RuntimeError("Listening Services requires Windows, macOS or Linux")
    mode = str((globals().get("kwargs") or {}).get("mode", "TCP") or "TCP").upper()
    if mode not in ("TCP", "HTTP"):
        raise ValueError("Mode must be TCP or HTTP")
    listeners = listening_sockets(os_alias)
    rows = []
    if mode == "TCP":
        rows = [service_record(item, os_alias) for item in listeners]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            web = list(pool.map(detect_web, listeners))
        rows = [dict(service_record(item, os_alias), **details)
                for item, details in zip(listeners, web) if details is not None]
    rows.sort(key=lambda row: (row["port"], row["pid"] if row["pid"] is not None else -1))
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()