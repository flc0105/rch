# server/scripts/jobs/port_scanner.py
# Real-time TCP port scanner with human-readable progress and JSON summary

JOB_METADATA = {
    "name": "port_scanner",
    "display_name": "Port Scanner",
    "description": "Scan TCP ports on a host in real time and summarize open services",
    "platforms": ["darwin", "windows", "linux"],
    "params": [
        {
            "name": "host",
            "type": "string",
            "required": False,
            "default": "127.0.0.1",
            "description": "Target host to scan, for example: 127.0.0.1, localhost, example.com"
        },
        {
            "name": "ports",
            "type": "string",
            "required": False,
            "default": (
                "20,21,22,23,25,53,80,88,110,111,135,139,143,389,443,445,"
                "465,587,631,636,873,902,993,995,1080,1433,1521,1883,2049,"
                "2375,2376,2483,2484,3000-3010,3306,3389,4000,4200,"
                "5000-5010,5173-5175,5432,5601,5672,5900,5985,5986,"
                "6379,6443,7001,7002,7474,8000-8010,8008,8080-8090,"
                "8161,8443,8500,8529,8888,9000-9010,9090,9200,9300,"
                "9418,9999,10000,11211,15672,27017,27018,28017,50000"
            ),
            "description": "Ports to scan. Supports single ports and ranges, for example: 22,80,443,8000-8080"
        },
        {
            "name": "timeout_seconds",
            "type": "number",
            "required": False,
            "default": 1.5,
            "min": 0.1,
            "description": "TCP connection timeout in seconds"
        },
        {
            "name": "probe_http",
            "type": "boolean",
            "required": False,
            "default": True,
            "description": "Probe HTTP/HTTPS information for open ports"
        }
    ]
}

import html
import json
import re
import socket
import ssl
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from client.jobs.job import Job


class PortScanner(Job):
    DEFAULT_HOST = "127.0.0.1"

    DEFAULT_PORTS = (
        "20,21,22,23,25,53,80,88,110,111,135,139,143,389,443,445,"
        "465,587,631,636,873,902,993,995,1080,1433,1521,1883,2049,"
        "2375,2376,2483,2484,3000-3010,3306,3389,4000,4200,"
        "5000-5010,5173-5175,5432,5601,5672,5900,5985,5986,"
        "6379,6443,7001,7002,7474,8000-8010,8008,8080-8090,"
        "8161,8443,8500,8529,8888,9000-9010,9090,9200,9300,"
        "9418,9999,10000,11211,15672,27017,27018,28017,50000"
    )

    SERVICE_NAMES = {
        20: "ftp-data",
        21: "ftp",
        22: "ssh",
        23: "telnet",
        25: "smtp",
        53: "dns",
        80: "http",
        88: "kerberos",
        110: "pop3",
        111: "rpcbind",
        135: "msrpc",
        139: "netbios-ssn",
        143: "imap",
        389: "ldap",
        443: "https",
        445: "smb",
        465: "smtps",
        587: "smtp-submission",
        631: "ipp",
        636: "ldaps",
        873: "rsync",
        902: "vmware-auth",
        993: "imaps",
        995: "pop3s",
        1080: "socks",
        1433: "mssql",
        1521: "oracle",
        1883: "mqtt",
        2049: "nfs",
        2375: "docker",
        2376: "docker-tls",
        2483: "oracle",
        2484: "oracle-tls",
        3000: "dev-server",
        3001: "dev-server",
        3306: "mysql",
        3389: "rdp",
        4000: "dev-server",
        4200: "angular-dev-server",
        5000: "flask/dev-server",
        5001: "dev-server",
        5173: "vite",
        5174: "vite",
        5175: "vite",
        5432: "postgresql",
        5601: "kibana",
        5672: "rabbitmq",
        5900: "vnc",
        5985: "winrm-http",
        5986: "winrm-https",
        6379: "redis",
        6443: "kubernetes-api",
        7001: "weblogic",
        7002: "weblogic-ssl",
        7474: "neo4j",
        8000: "dev/http",
        8008: "http-alt",
        8080: "http-proxy/dev",
        8081: "http-alt",
        8088: "http-alt",
        8161: "activemq",
        8443: "https-alt",
        8500: "consul",
        8529: "arangodb",
        8888: "jupyter/http-alt",
        9000: "dev/http-alt",
        9001: "dev/http-alt",
        9090: "prometheus/http-alt",
        9200: "elasticsearch",
        9300: "elasticsearch-transport",
        9418: "git",
        9999: "dev/http-alt",
        10000: "webmin",
        11211: "memcached",
        15672: "rabbitmq-management",
        27017: "mongodb",
        27018: "mongodb",
        28017: "mongodb-http",
        50000: "db2"
    }

    def __init__(self):
        super().__init__()
        self.host = self.DEFAULT_HOST
        self.ports_expr = self.DEFAULT_PORTS
        self.timeout_seconds = 1.5
        self.probe_http_enabled = True

    def on_context_bound(self):
        self.host = str(self.get_job_param("host", self.DEFAULT_HOST) or self.DEFAULT_HOST).strip()
        self.ports_expr = str(self.get_job_param("ports", self.DEFAULT_PORTS) or self.DEFAULT_PORTS).strip()
        self.timeout_seconds = float(self.get_job_param("timeout_seconds", 1.5) or 1.5)
        self.probe_http_enabled = self.to_bool(self.get_job_param("probe_http", True))

        if self.timeout_seconds <= 0:
            self.timeout_seconds = 1.5

    @staticmethod
    def to_bool(value):
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    @classmethod
    def guess_service_name(cls, port):
        return cls.SERVICE_NAMES.get(port)

    @staticmethod
    def validate_port(port):
        if port < 1 or port > 65535:
            raise ValueError(f"Invalid port: {port}. Port must be between 1 and 65535.")

    @classmethod
    def parse_ports(cls, ports_expr):
        """
        Supported examples:
          80
          22,80,443
          8000-8080
          22,80,443,5000-5009
        """
        if not ports_expr:
            raise ValueError("ports cannot be empty")

        ports = set()
        parts = [part.strip() for part in str(ports_expr).split(",") if part.strip()]

        for part in parts:
            if "-" in part:
                start_text, end_text = part.split("-", 1)
                start = int(start_text.strip())
                end = int(end_text.strip())

                if start > end:
                    raise ValueError(f"Invalid port range: {part}")

                cls.validate_port(start)
                cls.validate_port(end)

                for port in range(start, end + 1):
                    ports.add(port)
            else:
                port = int(part)
                cls.validate_port(port)
                ports.add(port)

        return sorted(ports)

    @staticmethod
    def extract_title(body):
        match = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
        if not match:
            return None

        title = html.unescape(match.group(1))
        title = re.sub(r"\s+", " ", title).strip()
        return title or None

    def tcp_connect(self, host, port):
        started_at = time.time()

        try:
            with socket.create_connection((host, port), timeout=self.timeout_seconds):
                elapsed_ms = round((time.time() - started_at) * 1000, 2)
                return {
                    "open": True,
                    "state": "open",
                    "elapsed_ms": elapsed_ms,
                    "error": None
                }

        except socket.timeout:
            elapsed_ms = round((time.time() - started_at) * 1000, 2)
            return {
                "open": False,
                "state": "filtered",
                "elapsed_ms": elapsed_ms,
                "error": "timeout"
            }

        except ConnectionRefusedError:
            elapsed_ms = round((time.time() - started_at) * 1000, 2)
            return {
                "open": False,
                "state": "closed",
                "elapsed_ms": elapsed_ms,
                "error": "connection refused"
            }

        except OSError as exc:
            elapsed_ms = round((time.time() - started_at) * 1000, 2)
            return {
                "open": False,
                "state": "error",
                "elapsed_ms": elapsed_ms,
                "error": str(exc)
            }

    def banner_probe(self, host, port):
        result = {
            "protocol_hint": None,
            "banner": None
        }

        try:
            with socket.create_connection((host, port), timeout=self.timeout_seconds) as sock:
                sock.settimeout(min(self.timeout_seconds, 2.0))

                try:
                    data = sock.recv(512)
                except socket.timeout:
                    data = b""

                if not data:
                    return result

                text = data.decode("utf-8", errors="ignore").strip()
                result["banner"] = text or None

                upper_text = text.upper()

                if upper_text.startswith("SSH-"):
                    result["protocol_hint"] = "ssh"
                elif upper_text.startswith("220") and "FTP" in upper_text:
                    result["protocol_hint"] = "ftp"
                elif upper_text.startswith("220") and "SMTP" in upper_text:
                    result["protocol_hint"] = "smtp"
                elif "FTP" in upper_text:
                    result["protocol_hint"] = "ftp"
                elif "SMTP" in upper_text:
                    result["protocol_hint"] = "smtp"

                return result

        except Exception:
            return result

    def http_probe(self, url, insecure=False):
        request = Request(
            url,
            headers={
                "User-Agent": "PortScannerJob/1.0",
                "Connection": "close"
            }
        )

        context = ssl._create_unverified_context() if insecure else None

        try:
            with urlopen(request, timeout=self.timeout_seconds + 1.0, context=context) as response:
                raw = response.read(65536)
                body = raw.decode("utf-8", errors="ignore")

                return {
                    "ok": True,
                    "status": getattr(response, "status", None),
                    "server_header": response.headers.get("Server"),
                    "content_type": response.headers.get("Content-Type"),
                    "title": self.extract_title(body),
                    "final_url": response.geturl()
                }

        except HTTPError as exc:
            body = ""

            try:
                body = exc.read(65536).decode("utf-8", errors="ignore")
            except Exception:
                pass

            return {
                "ok": True,
                "status": exc.code,
                "server_header": exc.headers.get("Server") if exc.headers else None,
                "content_type": exc.headers.get("Content-Type") if exc.headers else None,
                "title": self.extract_title(body),
                "final_url": url
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc)
            }

    def detect_web_service(self, host, port):
        http_url = f"http://{host}:{port}/"
        https_url = f"https://{host}:{port}/"

        http_result = self.http_probe(http_url, insecure=False)
        if http_result.get("ok"):
            http_result["scheme"] = "http"
            http_result["url"] = http_url
            return http_result

        if self.stop_event.is_set():
            return None

        https_result = self.http_probe(https_url, insecure=True)
        if https_result.get("ok"):
            https_result["scheme"] = "https"
            https_result["url"] = https_url
            return https_result

        return None

    def scan_one_port(self, host, port):
        tcp_result = self.tcp_connect(host, port)

        result = {
            "host": host,
            "port": port,
            "service_guess": self.guess_service_name(port),
            "state": tcp_result["state"],
            "tcp_open": tcp_result["open"],
            "elapsed_ms": tcp_result["elapsed_ms"],
            "error": tcp_result["error"],
            "protocol_hint": None,
            "banner": None,
            "web": None
        }

        if not tcp_result["open"]:
            return result

        if self.stop_event.is_set():
            return result

        banner = self.banner_probe(host, port)
        result["protocol_hint"] = banner.get("protocol_hint")
        result["banner"] = banner.get("banner")

        if self.probe_http_enabled and not self.stop_event.is_set():
            web = self.detect_web_service(host, port)

            if web:
                result["web"] = {
                    "scheme": web.get("scheme"),
                    "url": web.get("url"),
                    "status": web.get("status"),
                    "server_header": web.get("server_header"),
                    "content_type": web.get("content_type"),
                    "title": web.get("title"),
                    "final_url": web.get("final_url")
                }

                if not result["protocol_hint"]:
                    result["protocol_hint"] = web.get("scheme")

        return result

    def format_progress_message(self, result, index, total):
        port = result["port"]
        service = result.get("service_guess") or "-"
        elapsed_ms = result.get("elapsed_ms")
        state = result.get("state")
        error = result.get("error")
        protocol_hint = result.get("protocol_hint")
        banner = result.get("banner")
        web = result.get("web")

        prefix = f"[{index}/{total}] {result['host']}:{port} ({service})"

        if result["tcp_open"]:
            parts = [
                prefix,
                f"open",
                f"{elapsed_ms:.2f} ms"
            ]

            if protocol_hint:
                parts.append(f"protocol={protocol_hint}")

            if web:
                web_desc = web.get("url") or ""
                status = web.get("status")
                title = web.get("title")

                if status:
                    web_desc += f" status={status}"
                if title:
                    web_desc += f" title={title}"

                parts.append(f"web={web_desc}")

            if banner:
                clean_banner = re.sub(r"\s+", " ", banner).strip()
                if len(clean_banner) > 120:
                    clean_banner = clean_banner[:117] + "..."
                parts.append(f"banner={clean_banner}")

            return " | ".join(parts)

        if state == "closed":
            return f"{prefix} closed | refused | {elapsed_ms:.2f} ms"

        if state == "filtered":
            return f"{prefix} filtered | timeout | {elapsed_ms:.2f} ms"

        return f"{prefix} error | {error or 'unknown error'} | {elapsed_ms:.2f} ms"

    def run(self):
        self.mark_running()

        started_at = time.time()
        results = []
        open_ports = []
        web_services = []
        resolved_addresses = []

        try:
            if not self.host:
                self.send_to_server(1, "Invalid host parameter: host cannot be empty")
                return

            try:
                ports = self.parse_ports(self.ports_expr)
            except Exception as exc:
                self.send_to_server(1, f"Invalid ports parameter: {exc}")
                return

            try:
                infos = socket.getaddrinfo(self.host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
                resolved_addresses = sorted({item[4][0] for item in infos})
            except Exception as exc:
                self.send_to_server(1, f"DNS resolution failed for host {self.host}: {exc}")
                return

            self.send_to_server(
                1,
                f"Port scan started: host={self.host}, resolved={', '.join(resolved_addresses)}, "
                f"ports={len(ports)}, timeout={self.timeout_seconds}s, probe_http={self.probe_http_enabled}"
            )

            for index, port in enumerate(ports, start=1):
                if self.stop_event.is_set():
                    break

                result = self.scan_one_port(self.host, port)
                results.append(result)

                if result["tcp_open"]:
                    open_ports.append(result)

                    if result.get("web"):
                        web_info = dict(result["web"])
                        web_info["host"] = self.host
                        web_info["port"] = port
                        web_info["service_guess"] = result.get("service_guess")
                        web_services.append(web_info)

                self.send_to_server(
                    1,
                    self.format_progress_message(result, index, len(ports))
                )

            elapsed_seconds = round(time.time() - started_at, 2)
            cancelled = self.stop_event.is_set()

            summary = {
                "event": "scan_summary",
                "cancelled": cancelled,
                "host": self.host,
                "resolved_addresses": resolved_addresses,
                "ports_requested": self.ports_expr,
                "ports_total": len(ports),
                "ports_scanned": len(results),
                "open_count": len(open_ports),
                "closed_count": len([item for item in results if item["state"] == "closed"]),
                "filtered_count": len([item for item in results if item["state"] == "filtered"]),
                "error_count": len([item for item in results if item["state"] == "error"]),
                "web_service_count": len(web_services),
                "elapsed_seconds": elapsed_seconds,
                "open_ports": [
                    {
                        "host": item["host"],
                        "port": item["port"],
                        "service_guess": item["service_guess"],
                        "protocol_hint": item["protocol_hint"],
                        "banner": item["banner"],
                        "elapsed_ms": item["elapsed_ms"],
                        "web": item["web"]
                    }
                    for item in open_ports
                ],
                "web_services": web_services
            }

            if cancelled:
                self.send_to_server(1, "Port scan cancelled. Sending partial summary JSON.")
            else:
                self.send_to_server(1, "Port scan completed. Sending summary JSON.")

            self.send_to_server(
                1,
                json.dumps(summary, ensure_ascii=False, indent=2)
            )

        finally:
            self.mark_stopped()

    def stop(self, notify=True):
        self.request_stop(notify=notify)