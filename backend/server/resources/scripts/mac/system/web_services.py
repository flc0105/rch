#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""List locally reachable HTTP/HTTPS listening services on macOS as a flat JSON array.

Only Python's standard library and the macOS system utilities `lsof` and `ps`
are used. This script is read-only: it does not stop or change any process.

Notes:
  * This discovers TCP listeners first, then makes a short GET / request.
  * No redirects are followed. No connections to nonlocal remote addresses
    are made: only addresses found on local listening sockets are probed.
  * The Server field is copied *verbatim* from the HTTP response header. It
    is not proof of the server implementation or backend framework.
  * If multiple PIDs listen on the same numeric port, per-process information
    is null rather than arbitrarily assigning the port to one of them.
"""

import concurrent.futures
import html.parser
import http.client
import ipaddress
import json
import os
import platform
import re
import shlex
import ssl
import subprocess
import sys
import zlib


TIMEOUT_SECONDS = 1.5
MAX_HTML_BYTES = 131072
MAX_WORKERS = 10
SCRIPT_SUFFIXES = (".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".rb", ".php", ".jar")


class TitleParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.parts = []
        self.done = False

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "title" and not self.done:
            self.in_title = True

    def handle_endtag(self, tag):
        if tag.lower() == "title" and self.in_title:
            self.in_title = False
            self.done = True

    def handle_data(self, data):
        if self.in_title and len("".join(self.parts)) < 512:
            self.parts.append(data)


def find_title(content, content_type, content_encoding):
    if "text/html" not in content_type.lower() and "application/xhtml+xml" not in content_type.lower():
        return None

    encoding = content_encoding.lower().strip()
    if encoding in ("gzip", "deflate"):
        try:
            # Limit *decompressed* size to prevent huge expansion.
            inflater = zlib.decompressobj(16 + zlib.MAX_WBITS if encoding == "gzip" else zlib.MAX_WBITS)
            content = inflater.decompress(content, MAX_HTML_BYTES)
        except zlib.error:
            return None
    elif encoding not in ("", "identity"):
        return None

    charset_match = re.search(r"charset\s*=\s*['\"]?([\w-]+)", content_type, re.I)
    if not charset_match:
        charset_match = re.search(rb"<meta\b[^>]*charset\s*=\s*['\"]?([\w-]+)", content[:8192], re.I)
    charset = charset_match.group(1) if charset_match else "utf-8"
    if isinstance(charset, bytes):
        charset = charset.decode("ascii", "replace")

    try:
        decoded = content.decode(charset, "replace")
    except (LookupError, ValueError):
        decoded = content.decode("utf-8", "replace")

    parser = TitleParser()
    try:
        parser.feed(decoded)
    except Exception:
        return None
    title = " ".join("".join(parser.parts).split()).strip()
    return title[:250] if title else None


def parse_listeners(output):
    """Parse lsof -Fpcfn output; return {port: {pid: {addresses, name}}}."""
    ports = {}
    current_pid = None
    current_name = None
    has_file = False

    for raw_line in output.splitlines():
        if not raw_line:
            continue
        field, value = raw_line[0], raw_line[1:]
        if field == "p":
            current_pid = int(value) if value.isdecimal() else None
            current_name = None
            has_file = False
        elif field == "c":
            current_name = value
        elif field == "f":
            has_file = True
        elif field == "n" and has_file and current_pid is not None:
            # Typical -nP names: '*:8000', '127.0.0.1:8000', '[::1]:8000'.
            # Restrict to numeric ports: skip unrelated or malformed file names.
            if ":" not in value:
                continue
            address, port_text = value.rsplit(":", 1)
            if not port_text.isdecimal():
                continue
            port = int(port_text)
            if not 1 <= port <= 65535:
                continue
            address = address.strip("[]")
            if not address:
                continue
            entry = ports.setdefault(port, {}).setdefault(
                current_pid, {"addresses": set(), "name": current_name}
            )
            entry["addresses"].add(address)
            if current_name:
                entry["name"] = current_name
    return ports


def get_listeners():
    try:
        result = subprocess.run(
            ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpcfn"],
            capture_output=True, text=True, errors="replace", timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("无法运行 lsof：{}".format(exc)) from exc

    # lsof returns 1 when there are simply no matching listening sockets.
    if not result.stdout and result.returncode not in (0, 1):
        raise RuntimeError("lsof 查询失败：{}".format(result.stderr.strip() or result.returncode))
    if not result.stdout and result.stderr:
        print("lsof: " + result.stderr.strip(), file=sys.stderr)
    return parse_listeners(result.stdout)


def is_local_bind_address(address):
    # Addresses come from the operating system's own listening socket table.
    if address in ("*", "0.0.0.0", "::"):
        return True
    try:
        return not ipaddress.ip_address(address.split("%", 1)[0]).is_multicast
    except ValueError:
        return False


def probe_addresses(addresses):
    """Use loopback for wildcard sockets, actual local interface IPs otherwise."""
    ordered = []
    for addr in sorted(addresses):
        addr = addr.strip("[]")
        if not is_local_bind_address(addr):
            continue
        if addr in ("*", "0.0.0.0"):
            candidates = ["127.0.0.1"]
        elif addr == "::":
            candidates = ["::1", "127.0.0.1"]
        else:
            candidates = [addr]
        for candidate in candidates:
            if candidate not in ordered:
                ordered.append(candidate)
    # Prefer loopback (when available) over direct requests to a LAN address.
    ordered.sort(key=lambda a: (0 if a in ("127.0.0.1", "::1") else 1, ":" in a, a))
    return ordered


def make_url(scheme, address, port):
    address = "[{}]".format(address.replace("%", "%25")) if ":" in address else address
    return "{}://{}:{}/".format(scheme, address, port)


def request_http(address, port, use_tls):
    connection = None
    try:
        if use_tls:
            # Local discovery commonly encounters self-signed certificates.
            # No credentials are sent; disabling verification is ONLY for this probe.
            tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            tls_context.check_hostname = False
            tls_context.verify_mode = ssl.CERT_NONE
            tls_context.set_alpn_protocols(["http/1.1"])
            connection = http.client.HTTPSConnection(address, port, timeout=TIMEOUT_SECONDS, context=tls_context)
        else:
            connection = http.client.HTTPConnection(address, port, timeout=TIMEOUT_SECONDS)

        connection.request(
            "GET", "/",
            headers={
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                "Accept-Encoding": "gzip, deflate",
                "User-Agent": "LocalWebServiceInventory/1.0",
                "Connection": "close",
            }
        )
        response = connection.getresponse()  # A successfully parsed HTTP/1.x response.
        content_type = response.getheader("Content-Type", "")
        content_encoding = response.getheader("Content-Encoding", "")
        server = response.getheader("Server")
        title = None
        if "text/html" in content_type.lower() or "application/xhtml+xml" in content_type.lower():
            content = response.read(MAX_HTML_BYTES)
            title = find_title(content, content_type, content_encoding)
        return {
            "url": make_url("https" if use_tls else "http", address, port),
            "http_status": response.status,
            "title": title,
            "server_header": server[:300] if server else None,
        }
    except (OSError, ValueError, ssl.SSLError, http.client.HTTPException):
        return None
    finally:
        if connection is not None:
            connection.close()


def probe_port(port, by_pid):
    addresses = set()
    for details in by_pid.values():
        addresses.update(details["addresses"])
    targets = probe_addresses(addresses)
    for address in targets:
        # Probe TLS first to avoid classifying an HTTPS endpoint's cleartext
        # redirect/error page as its actual service protocol.
        for use_tls in (True, False):
            result = request_http(address, port, use_tls)
            if result is not None:
                return result
    return None


def ps_value(pid, field):
    try:
        result = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", field + "="],
            capture_output=True, text=True, errors="replace", timeout=3, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def process_cwd(pid):
    try:
        result = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True, text=True, errors="replace", timeout=3, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in result.stdout.splitlines():
        if line.startswith("n/"):
            return line[1:]
    return None


def extract_script_path(command, pid):
    if not command:
        return None, None
    try:
        args = shlex.split(command)
    except ValueError:
        return None, None
    if not args:
        return None, None

    base = os.path.basename(args[0]).lower()
    # `python -m package` is a module, not necessarily a script on disk.
    if base.startswith("python"):
        for i, token in enumerate(args[1:], 1):
            if token == "-m" and i + 1 < len(args):
                return None, args[i + 1]
            if token in ("-c",):
                return None, None
    if base in ("node", "bun", "deno") and any(x in args[1:] for x in ("-e", "--eval")):
        return None, None

    for token in args[1:]:
        if token.startswith("-"):
            continue
        if not token.lower().endswith(SCRIPT_SUFFIXES):
            continue
        # Confirm a plausible path rather than treating arbitrary arguments
        # such as --log-file=foo.py as a script.
        if os.path.isabs(token):
            return os.path.normpath(token), None
        cwd = process_cwd(pid)
        if cwd:
            return os.path.abspath(os.path.join(cwd, token)), None
        return None, None
    return None, None


def process_details(pid, name):
    command = ps_value(pid, "command")
    comm = ps_value(pid, "comm")
    executable_path = comm if comm and os.path.isabs(comm) else None
    script_path, module_name = extract_script_path(command, pid)
    process_name = name or (os.path.basename(comm) if comm else None)
    service_name = os.path.basename(script_path) if script_path else (module_name or process_name)
    return {
        "service_name": service_name,
        "script_path": script_path,
        "pid": pid,
        "process_name": process_name,
        "executable_path": executable_path,
        "command": command,
    }


def make_record(port, by_pid, http_data):
    owners = sorted(by_pid)
    if len(owners) == 1:
        pid = owners[0]
        proc = process_details(pid, by_pid[pid]["name"])
    else:
        # Multiple processes can share one TCP port with different bind
        # addresses/SO_REUSEPORT; don't fabricate a single owner.
        proc = {
            "service_name": None, "script_path": None, "pid": None,
            "process_name": None, "executable_path": None, "command": None,
        }
    return {
        "port": port,
        "service_name": proc["service_name"],
        "script_path": proc["script_path"],
        "pid": proc["pid"],
        "process_name": proc["process_name"],
        "executable_path": proc["executable_path"],
        "command": proc["command"],
        "url": http_data["url"],
        "http_status": http_data["http_status"],
        "title": http_data["title"],
        "server_header": http_data["server_header"],
    }


def main():
    if platform.system() != "Darwin":
        print("本脚本仅支持 macOS。", file=sys.stderr)
        return
    try:
        listeners = get_listeners()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return
    records = []
    if listeners:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(probe_port, port, by_pid): (port, by_pid)
                       for port, by_pid in listeners.items()}
            for future in concurrent.futures.as_completed(futures):
                port, by_pid = futures[future]
                try:
                    http_data = future.result()
                except Exception:
                    http_data = None
                if http_data is not None:
                    records.append(make_record(port, by_pid, http_data))
    records.sort(key=lambda rec: rec["port"])
    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
