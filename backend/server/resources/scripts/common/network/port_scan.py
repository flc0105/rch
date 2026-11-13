SCRIPT_METADATA = {
    "name": "common/network/port_scan",
    "display_name": "Port Scan",
    "description": "Scan TCP ports or identify HTTP/HTTPS services",
    "platforms": ["common"],
    "category": "Recon",
    "params": [
        {
            "name": "mode",
            "type": "select",
            "required": False,
            "default": "tcp",
            "options": ["tcp", "http"],
            "description": "Scan mode"
        },
        {
            "name": "host",
            "type": "string",
            "required": False,
            "default": "127.0.0.1",
            "description": "Target hostname or IP address"
        },
        {
            "name": "ports",
            "type": "string",
            "required": False,
            "default": "22,80,443,8080-8089,8443,9443,9999",
            "description": "Ports and ranges, for example: 22,80,443,8080-8089"
        },
        {
            "name": "timeout",
            "type": "number",
            "required": False,
            "default": 1.0,
            "min": 0.1,
            "description": "Connection timeout in seconds"
        },
        {
            "name": "json",
            "type": "boolean",
            "required": False,
            "default": False,
            "description": "Output a JSON array for Terminal table rendering"
        }
    ]
}

import errno
import html
from http.client import HTTPException
import json
import re
import socket
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)


def parse_ports(expression):
    ports = set()

    for part in str(expression).split(","):
        part = part.strip()
        if not part:
            raise ValueError("Empty port entry")

        bounds = part.split("-")
        if len(bounds) not in (1, 2) or not all(item.strip().isdecimal() for item in bounds):
            raise ValueError("Invalid port entry: {}".format(part))

        start = int(bounds[0].strip())
        end = int(bounds[-1].strip())
        if not (1 <= start <= end <= 65535):
            raise ValueError("Port out of range or reversed: {}".format(part))

        ports.update(range(start, end + 1))

    return sorted(ports)


def tcp_probe(host, port, timeout):
    start = time.perf_counter()
    state = "open"
    error = None

    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except ConnectionRefusedError:
        state = "closed"
        error = "connection refused"
    except (socket.timeout, TimeoutError):
        state = "filtered"
        error = "timeout"
    except OSError as exc:
        if exc.errno == errno.ECONNREFUSED:
            state = "closed"
            error = "connection refused"
        elif exc.errno == errno.ETIMEDOUT:
            state = "filtered"
            error = "timeout"
        else:
            state = "error"
            error = str(exc)

    return {
        "host": host,
        "port": port,
        "state": state,
        "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
        "error": error,
    }


def extract_title(body):
    match = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    if not match:
        return None
    title = html.unescape(match.group(1))
    title = re.sub(r"\s+", " ", title).strip()
    return title or None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def http_probe(opener, url, timeout):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Connection": "close"})

    try:
        response = opener.open(request, timeout=timeout)
    except HTTPError as exc:
        # HTTPError carries valid HTTP responses, including 401, 403 and 404.
        response = exc
    except (URLError, OSError, ValueError, ssl.SSLError, HTTPException):
        return None

    with response:
        try:
            raw = response.read(65536)
        except (OSError, ValueError, HTTPException):
            raw = b""

        body = raw.decode("utf-8", errors="replace")
        return {
            "status": response.code,
            "server_header": response.headers.get("Server"),
            "content_type": response.headers.get("Content-Type"),
            "title": extract_title(body),
            "final_url": response.geturl(),
        }


def http_scan(opener, host, port, timeout):
    url_host = "[{}]".format(host) if ":" in host and not host.startswith("[") else host

    for scheme in ("http", "https"):
        url = "{}://{}:{}/".format(scheme, url_host, port)
        result = http_probe(opener, url, timeout)
        if result is not None:
            return {
                "host": host,
                "port": port,
                "scheme": scheme,
                "url": url,
                "status": result["status"],
                "server_header": result["server_header"],
                "content_type": result["content_type"],
                "title": result["title"],
                "final_url": result["final_url"],
            }

    return None


def main():
    params = kwargs
    json_mode = params["json"]

    try:
        mode = params["mode"]
        if mode not in ("tcp", "http"):
            raise ValueError("Invalid mode: {}".format(mode))

        host = params["host"].strip()
        if not host:
            raise ValueError("Host cannot be empty")

        ports = parse_ports(params["ports"])
        timeout = float(params["timeout"])
        if not (0 < timeout < float("inf")):
            raise ValueError("Timeout must be a positive finite number")
    except (ValueError, TypeError, KeyError) as exc:
        if json_mode:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            print("Error: {}".format(exc), flush=True)
        return

    rows = [] if json_mode else None

    if mode == "http":
        # A scan must connect directly to the target, not through system proxy settings.
        opener = build_opener(
            ProxyHandler({}),
            HTTPHandler(),
            HTTPSHandler(context=ssl._create_unverified_context()),
            NoRedirect(),
        )

    for port in ports:
        if mode == "tcp":
            row = tcp_probe(host, port, timeout)
            if json_mode:
                rows.append(row)
            else:
                line = "{}:{:<5} {:<8} {:>7.1f} ms".format(
                    row["host"], row["port"], row["state"], row["elapsed_ms"]
                )
                if row["error"]:
                    line += "  {}".format(row["error"])
                print(line, flush=True)
        else:
            row = http_scan(opener, host, port, timeout)
            if json_mode:
                if row is not None:
                    rows.append(row)
            elif row is None:
                print("{}:{} no HTTP/HTTPS service".format(host, port), flush=True)
            else:
                message = "{}:{} {} {} {}".format(
                    host, port, row["scheme"].upper(), row["status"], row["url"]
                )
                if row["title"]:
                    message += "  title={}".format(row["title"])
                print(message, flush=True)

    if json_mode:
        print(json.dumps(rows, ensure_ascii=False, indent=2))


main()