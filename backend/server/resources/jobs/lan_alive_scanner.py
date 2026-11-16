# server/scripts/jobs/lan_alive_scanner.py
# LAN alive scanner using distinctive TCP probes only.

JOB_METADATA = {
    "name": "lan_alive_scanner",
    "display_name": "LAN Alive Scanner",
    "description": "Scan LAN hosts using distinctive TCP probes only",
    "platforms": ["darwin", "windows", "linux"],
    "params": [
        {
            "name": "subnet",
            "type": "string",
            "required": False,
            "default": "",
            "description": "CIDR subnet to scan, for example: 192.168.1.0/24. Leave empty to auto-detect local /24."
        },
        {
            "name": "timeout_seconds",
            "type": "number",
            "required": False,
            "default": 0.6,
            "min": 0.1,
            "description": "TCP connection timeout in seconds"
        },
        {
            "name": "max_workers",
            "type": "integer",
            "required": False,
            "default": 96,
            "min": 1,
            "description": "Concurrent scan workers"
        },
        {
            "name": "tcp_probe_ports",
            "type": "string",
            "required": False,
            "default": (
                "21,22,23,53,80,135,139,443,445,548,554,631,"
                "3389,5357,5555,5900,62078,7000,8008,8009,"
                "8080,8443,9100,32400"
            ),
            "description": "Distinctive TCP ports used to detect hosts and infer device type"
        },
        {
            "name": "probe_http",
            "type": "boolean",
            "required": False,
            "default": True,
            "description": "Probe HTTP/HTTPS title and headers on open web-like ports"
        },
        {
            "name": "probe_banners",
            "type": "boolean",
            "required": False,
            "default": True,
            "description": "Try to read passive banners from open TCP ports"
        },
        {
            "name": "max_hosts",
            "type": "integer",
            "required": False,
            "default": 4096,
            "min": 1,
            "description": "Safety limit for number of hosts to scan"
        }
    ]
}

import concurrent.futures
import html
import ipaddress
import json
import re
import socket
import ssl
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from client.jobs.job import Job


class LanAliveScanner(Job):
    AUTO_DETECT_PREFIX_LENGTH = 24

    DEFAULT_TCP_PROBE_PORTS = (
        "21,22,23,53,80,135,139,443,445,548,554,631,"
        "3389,5357,5555,5900,62078,7000,8008,8009,"
        "8080,8443,9100,32400"
    )

    SERVICE_NAMES = {
        21: "ftp",
        22: "ssh",
        23: "telnet",
        53: "dns",
        80: "http",
        135: "msrpc",
        139: "netbios-ssn",
        443: "https",
        445: "smb",
        548: "afp",
        554: "rtsp",
        631: "ipp/cups",
        3389: "rdp",
        5357: "wsdapi",
        5555: "adb",
        5900: "vnc",
        62078: "iphone-sync",
        7000: "airplay",
        8008: "cast/http",
        8009: "cast",
        8080: "http-alt",
        8443: "https-alt",
        9100: "printer-raw",
        32400: "plex"
    }

    WEB_PORTS = {
        80,
        443,
        5357,
        7000,
        8008,
        8080,
        8443,
        32400
    }

    HTTPS_FIRST_PORTS = {
        443,
        8443
    }

    def __init__(self):
        super().__init__()

        self.subnet = ""
        self.timeout_seconds = 0.6
        self.max_workers = 96
        self.tcp_probe_ports_expr = self.DEFAULT_TCP_PROBE_PORTS
        self.tcp_probe_ports = []

        self.probe_http_enabled = True
        self.probe_banners_enabled = True
        self.max_hosts = 4096

        self.auto_detected = False
        self.local_ip = None

    def on_context_bound(self):
        self.subnet = str(self.get_job_param("subnet", "") or "").strip()
        self.timeout_seconds = float(self.get_job_param("timeout_seconds", 0.6) or 0.6)
        self.max_workers = int(self.get_job_param("max_workers", 96) or 96)

        self.tcp_probe_ports_expr = str(
            self.get_job_param("tcp_probe_ports", self.DEFAULT_TCP_PROBE_PORTS)
            or self.DEFAULT_TCP_PROBE_PORTS
        ).strip()

        self.probe_http_enabled = self.to_bool(self.get_job_param("probe_http", True))
        self.probe_banners_enabled = self.to_bool(self.get_job_param("probe_banners", True))
        self.max_hosts = int(self.get_job_param("max_hosts", 4096) or 4096)

        self.timeout_seconds = max(0.1, self.timeout_seconds)
        self.max_workers = min(max(1, self.max_workers), 256)
        self.max_hosts = max(1, self.max_hosts)
        self.tcp_probe_ports = self.parse_ports(self.tcp_probe_ports_expr)

    @staticmethod
    def to_bool(value):
        if isinstance(value, bool):
            return value

        if value is None:
            return False

        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    @staticmethod
    def validate_port(port):
        if port < 1 or port > 65535:
            raise ValueError(f"Invalid port: {port}. Port must be between 1 and 65535.")

    @classmethod
    def parse_ports(cls, ports_expr):
        if not ports_expr:
            return []

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
    def get_primary_ipv4():
        """
        Pure Python local IPv4 detection.

        UDP connect does not send application data. It only asks the OS
        which local address would be used for that route.
        """
        targets = [
            ("8.8.8.8", 80),
            ("1.1.1.1", 80),
            ("223.5.5.5", 80)
        ]

        for target in targets:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.connect(target)
                    ip = sock.getsockname()[0]

                    if ip and not ip.startswith("127."):
                        return ip
            except Exception:
                pass

        try:
            hostname = socket.gethostname()
            infos = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)

            for info in infos:
                ip = info[4][0]

                if ip and not ip.startswith("127."):
                    return ip
        except Exception:
            pass

        return None

    @staticmethod
    def estimate_host_count(network):
        if network.prefixlen == 32:
            return 1

        if network.prefixlen == 31:
            return 2

        return max(network.num_addresses - 2, 0)

    def parse_or_detect_subnet(self):
        self.local_ip = self.get_primary_ipv4()

        if self.subnet:
            network = ipaddress.ip_network(self.subnet, strict=False)
            self.auto_detected = False
        else:
            if not self.local_ip:
                raise ValueError(
                    "subnet is empty and local IPv4 address could not be detected. "
                    "Please provide subnet manually, for example: 192.168.1.0/24"
                )

            network = ipaddress.ip_network(
                f"{self.local_ip}/{self.AUTO_DETECT_PREFIX_LENGTH}",
                strict=False
            )
            self.auto_detected = True

        if network.version != 4:
            raise ValueError("Only IPv4 subnet scanning is supported, for example: 192.168.1.0/24")

        host_count = self.estimate_host_count(network)

        if host_count > self.max_hosts:
            raise ValueError(
                f"Subnet is too large: {network} contains about {host_count} hosts. "
                f"Current max_hosts is {self.max_hosts}."
            )

        return network

    def tcp_probe(self, ip, port):
        started_at = time.time()

        try:
            with socket.create_connection((ip, port), timeout=self.timeout_seconds):
                elapsed_ms = round((time.time() - started_at) * 1000, 2)

                return {
                    "port": port,
                    "service_guess": self.SERVICE_NAMES.get(port),
                    "state": "open",
                    "elapsed_ms": elapsed_ms,
                    "error": None
                }

        except ConnectionRefusedError:
            elapsed_ms = round((time.time() - started_at) * 1000, 2)

            return {
                "port": port,
                "service_guess": self.SERVICE_NAMES.get(port),
                "state": "refused",
                "elapsed_ms": elapsed_ms,
                "error": "connection refused"
            }

        except socket.timeout:
            elapsed_ms = round((time.time() - started_at) * 1000, 2)

            return {
                "port": port,
                "service_guess": self.SERVICE_NAMES.get(port),
                "state": "timeout",
                "elapsed_ms": elapsed_ms,
                "error": "timeout"
            }

        except OSError as exc:
            elapsed_ms = round((time.time() - started_at) * 1000, 2)
            message = str(exc).lower()

            if "refused" in message:
                state = "refused"
            elif "timed out" in message or "timeout" in message:
                state = "timeout"
            elif "no route" in message or "unreachable" in message:
                state = "unreachable"
            else:
                state = "error"

            return {
                "port": port,
                "service_guess": self.SERVICE_NAMES.get(port),
                "state": state,
                "elapsed_ms": elapsed_ms,
                "error": str(exc)
            }

    @staticmethod
    def clean_banner(text, limit=240):
        if not text:
            return None

        text = text.replace("\x00", "")
        text = re.sub(r"[\r\n\t]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        if not text:
            return None

        if len(text) > limit:
            text = text[:limit - 3] + "..."

        return text

    def banner_probe(self, ip, port):
        result = {
            "protocol_hint": None,
            "banner": None
        }

        try:
            with socket.create_connection((ip, port), timeout=self.timeout_seconds) as sock:
                sock.settimeout(min(self.timeout_seconds, 1.5))

                try:
                    data = sock.recv(512)
                except socket.timeout:
                    data = b""

                if not data:
                    return result

                raw_text = data.decode("utf-8", errors="ignore").strip()

                if not raw_text:
                    return result

                first_line = raw_text.splitlines()[0].strip() if raw_text.splitlines() else raw_text
                upper = first_line.upper()

                if upper.startswith("SSH-"):
                    result["protocol_hint"] = "ssh"
                    result["banner"] = self.clean_banner(first_line)
                elif upper.startswith("220") and "FTP" in upper:
                    result["protocol_hint"] = "ftp"
                    result["banner"] = self.clean_banner(first_line)
                elif upper.startswith("RFB "):
                    result["protocol_hint"] = "vnc"
                    result["banner"] = self.clean_banner(first_line)
                elif "RTSP" in upper:
                    result["protocol_hint"] = "rtsp"
                    result["banner"] = self.clean_banner(first_line)
                else:
                    result["banner"] = self.clean_banner(raw_text)

                return result

        except Exception:
            return result

    @staticmethod
    def extract_title(body):
        match = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)

        if not match:
            return None

        title = html.unescape(match.group(1))
        title = re.sub(r"\s+", " ", title).strip()

        return title or None

    def http_probe(self, url, insecure=False):
        request = Request(
            url,
            headers={
                "User-Agent": "LanAliveScannerJob/1.0",
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

    def detect_web_service(self, ip, port):
        if port in self.HTTPS_FIRST_PORTS:
            candidates = [
                ("https", f"https://{ip}:{port}/", True),
                ("http", f"http://{ip}:{port}/", False)
            ]
        else:
            candidates = [
                ("http", f"http://{ip}:{port}/", False),
                ("https", f"https://{ip}:{port}/", True)
            ]

        for scheme, url, insecure in candidates:
            if self.stop_event.is_set():
                return None

            result = self.http_probe(url, insecure=insecure)

            if result.get("ok"):
                result["scheme"] = scheme
                result["url"] = url
                return result

        return None

    @staticmethod
    def top_guess(score_map):
        if not score_map:
            return {
                "label": "unknown",
                "confidence": "low"
            }

        label, score = max(score_map.items(), key=lambda item: item[1])

        if score >= 5:
            confidence = "high"
        elif score >= 3:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "label": label,
            "confidence": confidence,
            "score": score
        }

    def infer_device_and_os(self, ip, open_ports, web_services, banners, network):
        port_set = {item["port"] for item in open_ports}

        text_blob = " ".join(
            [
                str(item.get("title") or "")
                + " "
                + str(item.get("server_header") or "")
                + " "
                + str(item.get("content_type") or "")
                for item in web_services
            ]
            + [str(item.get("banner") or "") for item in banners]
        ).lower()

        os_scores = {}
        device_scores = {}
        evidence = []

        def add_os(label, score, reason):
            os_scores[label] = os_scores.get(label, 0) + score
            evidence.append(reason)

        def add_device(label, score, reason):
            device_scores[label] = device_scores.get(label, 0) + score
            evidence.append(reason)

        if self.local_ip and ip == self.local_ip:
            add_device("local_machine", 6, "IP matches local scanner address")

        if port_set & {135, 139, 445, 3389, 5357}:
            add_os("windows", 4, "Windows-related TCP ports detected")
            add_device("windows_pc_or_server", 3, "SMB/RPC/RDP/WSDAPI-like ports detected")

        if "microsoft-iis" in text_blob or "microsoft-httpapi" in text_blob or "iis windows" in text_blob:
            add_os("windows", 4, "Microsoft HTTP service signature detected")
            add_device("windows_pc_or_server", 3, "Microsoft HTTP service detected")

        if 3389 in port_set:
            add_device("remote_desktop_host", 4, "RDP port 3389 is open")

        if 5900 in port_set or "rfb " in text_blob:
            add_device("remote_desktop_host", 3, "VNC/RFB signal detected")

        if 22 in port_set:
            add_os("linux_unix_or_network_device", 2, "SSH port 22 is open")

        if "ssh-2.0-openssh" in text_blob:
            add_os("linux_unix_or_network_device", 3, "OpenSSH banner detected")
            add_device("ssh_managed_host", 2, "SSH service detected")

        if "ssh-2.0-dropbear" in text_blob:
            add_os("embedded_linux_or_network_device", 4, "Dropbear SSH banner detected")
            add_device("embedded_or_network_device", 3, "Dropbear SSH is common on embedded/network devices")

        if port_set & {548, 62078, 7000} or "airtunes" in text_blob or "airplay" in text_blob:
            add_os("apple_macos_ios_or_airplay_device", 3, "Apple/AirPlay-related signal detected")
            add_device("apple_or_airplay_device", 3, "Apple/AirPlay-related service detected")

        if 62078 in port_set:
            add_device("ios_device", 5, "iPhone sync port 62078 is open")

        if 7000 in port_set:
            add_device("airplay_device", 4, "AirPlay-like port 7000 is open")

        if 5555 in port_set:
            add_os("android_or_embedded_linux", 5, "ADB port 5555 is open")
            add_device("android_adb_device", 5, "ADB service detected")

        if port_set & {631, 9100}:
            add_device("printer_or_print_server", 5, "Printing-related ports detected")

        if "ipp" in text_blob or "cups" in text_blob:
            add_device("printer_or_print_server", 3, "IPP/CUPS service signature detected")

        if 554 in port_set or "rtsp" in text_blob:
            add_device("camera_or_nvr", 5, "RTSP signal detected")

        if port_set & {8008, 8009}:
            add_device("cast_or_media_device", 4, "Cast-related ports detected")

        if 32400 in port_set or "plex" in text_blob:
            add_device("media_server", 5, "Media server signal detected")

        try:
            first_usable_ip = str(next(network.hosts()))
        except Exception:
            first_usable_ip = None

        web_ports = port_set & {80, 443, 8080, 8443}

        if ip == first_usable_ip and 53 in port_set and web_ports:
            add_device("router_or_gateway", 5, "First usable IP with DNS and web management ports detected")
        elif 53 in port_set and web_ports:
            add_device("router_dns_or_network_appliance", 3, "DNS plus web management ports detected")

        if port_set & {80, 443, 8080, 8443} and not device_scores:
            add_device("web_management_device", 2, "Web management port detected")

        if port_set and not os_scores:
            add_os("unknown_tcp_device", 1, "TCP response detected but OS fingerprint is weak")

        if port_set and not device_scores:
            add_device("unknown_network_device", 1, "TCP response detected but device type is unclear")

        return {
            "os_guess": self.top_guess(os_scores),
            "device_type_guess": self.top_guess(device_scores),
            "evidence": sorted(set(evidence))
        }

    def new_empty_result(self, ip):
        return {
            "ip": ip,
            "alive": False,
            "alive_methods": [],
            "open_ports": [],
            "web_services": [],
            "banners": [],
            "tcp_probe_summary": {
                "open_count": 0,
                "refused_count": 0,
                "timeout_count": 0,
                "unreachable_count": 0,
                "error_count": 0
            },
            "os_guess": {
                "label": "unknown",
                "confidence": "low"
            },
            "device_type_guess": {
                "label": "unknown",
                "confidence": "low"
            },
            "fingerprint_evidence": []
        }

    def scan_host(self, ip, network):
        result = self.new_empty_result(ip)
        alive_methods = set()

        if self.stop_event.is_set():
            return result

        for port in self.tcp_probe_ports:
            if self.stop_event.is_set():
                break

            probe = self.tcp_probe(ip, port)
            state = probe["state"]

            if state == "open":
                result["tcp_probe_summary"]["open_count"] += 1
                alive_methods.add("tcp_open")

                result["open_ports"].append({
                    "port": port,
                    "service_guess": probe.get("service_guess"),
                    "elapsed_ms": probe.get("elapsed_ms")
                })

            elif state == "refused":
                result["tcp_probe_summary"]["refused_count"] += 1
                alive_methods.add("tcp_refused")

            elif state == "timeout":
                result["tcp_probe_summary"]["timeout_count"] += 1

            elif state == "unreachable":
                result["tcp_probe_summary"]["unreachable_count"] += 1

            else:
                result["tcp_probe_summary"]["error_count"] += 1

        result["alive_methods"] = sorted(alive_methods)
        result["alive"] = bool(alive_methods)

        if not result["alive"]:
            return result

        if self.probe_banners_enabled and not self.stop_event.is_set():
            for item in result["open_ports"]:
                if self.stop_event.is_set():
                    break

                port = item["port"]
                banner = self.banner_probe(ip, port)

                if banner.get("banner") or banner.get("protocol_hint"):
                    result["banners"].append({
                        "port": port,
                        "service_guess": item.get("service_guess"),
                        "protocol_hint": banner.get("protocol_hint"),
                        "banner": banner.get("banner")
                    })

        if self.probe_http_enabled and not self.stop_event.is_set():
            for item in result["open_ports"]:
                if self.stop_event.is_set():
                    break

                port = item["port"]

                if port not in self.WEB_PORTS:
                    continue

                web = self.detect_web_service(ip, port)

                if web:
                    result["web_services"].append({
                        "port": port,
                        "scheme": web.get("scheme"),
                        "url": web.get("url"),
                        "status": web.get("status"),
                        "server_header": web.get("server_header"),
                        "content_type": web.get("content_type"),
                        "title": web.get("title"),
                        "final_url": web.get("final_url")
                    })

        fingerprint = self.infer_device_and_os(
            ip=ip,
            open_ports=result["open_ports"],
            web_services=result["web_services"],
            banners=result["banners"],
            network=network
        )

        result["os_guess"] = fingerprint["os_guess"]
        result["device_type_guess"] = fingerprint["device_type_guess"]
        result["fingerprint_evidence"] = fingerprint["evidence"]

        return result

    def format_progress_message(self, result, completed, total):
        prefix = f"[{completed}/{total}] {result['ip']}"

        if not result["alive"]:
            return f"{prefix} no response"

        methods = ",".join(result.get("alive_methods") or ["unknown"])

        open_ports = result.get("open_ports") or []

        if open_ports:
            open_desc_items = []

            for item in open_ports[:8]:
                service = item.get("service_guess") or "-"
                open_desc_items.append(f"{item['port']}/{service}")

            open_desc = ", ".join(open_desc_items)

            if len(open_ports) > 8:
                open_desc += f", +{len(open_ports) - 8} more"
        else:
            open_desc = "none"

        os_guess = result.get("os_guess") or {}
        device_guess = result.get("device_type_guess") or {}

        return (
            f"{prefix} alive | methods={methods} | open={open_desc} | "
            f"os≈{os_guess.get('label', 'unknown')}({os_guess.get('confidence', 'low')}) | "
            f"device≈{device_guess.get('label', 'unknown')}({device_guess.get('confidence', 'low')})"
        )

    def iter_scan_results(self, hosts, network):
        max_pending = max(self.max_workers * 2, self.max_workers)
        host_iter = iter(hosts)
        pending = {}

        def submit_next(executor):
            try:
                ip = next(host_iter)
            except StopIteration:
                return False

            future = executor.submit(self.scan_host, ip, network)
            pending[future] = ip
            return True

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for _ in range(min(max_pending, len(hosts))):
                submit_next(executor)

            while pending:
                if self.stop_event.is_set():
                    for future in pending:
                        future.cancel()
                    break

                done, _ = concurrent.futures.wait(
                    pending,
                    timeout=0.2,
                    return_when=concurrent.futures.FIRST_COMPLETED
                )

                if not done:
                    continue

                for future in done:
                    ip = pending.pop(future)

                    try:
                        result = future.result()
                    except Exception as exc:
                        result = self.new_empty_result(ip)
                        result["error"] = str(exc)

                    yield result

                    if not self.stop_event.is_set():
                        submit_next(executor)

    @staticmethod
    def sort_by_ip(items):
        return sorted(items, key=lambda item: ipaddress.ip_address(item["ip"]))

    def run(self):
        self.mark_running()

        started_at = time.time()
        scanned_results = []

        try:
            try:
                network = self.parse_or_detect_subnet()
                hosts = [str(ip) for ip in network.hosts()]
            except Exception as exc:
                self.send_to_server(1, f"Invalid subnet parameter: {exc}")
                return

            if not self.tcp_probe_ports:
                self.send_to_server(1, "No TCP probe ports configured.")
                return

            if not hosts:
                self.send_to_server(1, f"No usable hosts found in subnet: {network}")
                return

            if self.auto_detected:
                self.send_to_server(
                    1,
                    (
                        f"Subnet is empty. Auto-detected local IPv4={self.local_ip}, "
                        f"using subnet={network}."
                    )
                )

            self.send_to_server(
                1,
                (
                    f"LAN TCP scan started: subnet={network}, hosts={len(hosts)}, "
                    f"timeout={self.timeout_seconds}s, workers={self.max_workers}, "
                    f"tcp_ports={self.tcp_probe_ports}"
                )
            )

            for result in self.iter_scan_results(hosts, network):
                scanned_results.append(result)

                self.send_to_server(
                    1,
                    self.format_progress_message(
                        result,
                        len(scanned_results),
                        len(hosts)
                    )
                )

                if self.stop_event.is_set():
                    break

            elapsed_seconds = round(time.time() - started_at, 2)
            cancelled = self.stop_event.is_set()

            scanned_results = self.sort_by_ip(scanned_results)
            alive_hosts = self.sort_by_ip([item for item in scanned_results if item.get("alive")])

            tcp_open_alive_count = len([
                item for item in scanned_results
                if "tcp_open" in item.get("alive_methods", [])
            ])

            tcp_refused_alive_count = len([
                item for item in scanned_results
                if "tcp_refused" in item.get("alive_methods", [])
            ])

            open_service_hosts_count = len([
                item for item in scanned_results
                if item.get("open_ports")
            ])

            refused_only_hosts = [
                item for item in alive_hosts
                if item.get("alive_methods") == ["tcp_refused"]
            ]

            summary = {
                "event": "lan_tcp_scan_summary",
                "cancelled": cancelled,
                "auto_detected_subnet": self.auto_detected,
                "local_ip": self.local_ip,
                "subnet": str(network),
                "network_address": str(network.network_address),
                "broadcast_address": str(network.broadcast_address),
                "prefix_length": network.prefixlen,
                "hosts_total": len(hosts),
                "hosts_scanned": len(scanned_results),
                "alive_count": len(alive_hosts),
                "no_response_count": len([item for item in scanned_results if not item.get("alive")]),
                "tcp_open_alive_count": tcp_open_alive_count,
                "tcp_refused_alive_count": tcp_refused_alive_count,
                "open_service_hosts_count": open_service_hosts_count,
                "refused_only_count": len(refused_only_hosts),
                "elapsed_seconds": elapsed_seconds,
                "settings": {
                    "timeout_seconds": self.timeout_seconds,
                    "max_workers": self.max_workers,
                    "tcp_probe_ports": self.tcp_probe_ports,
                    "probe_http": self.probe_http_enabled,
                    "probe_banners": self.probe_banners_enabled,
                    "max_hosts": self.max_hosts,
                    "auto_detect_prefix_length": self.AUTO_DETECT_PREFIX_LENGTH
                },
                "alive_hosts": alive_hosts
            }

            if cancelled:
                self.send_to_server(1, "LAN TCP scan cancelled. Sending partial summary JSON.")
            else:
                self.send_to_server(1, "LAN TCP scan completed. Sending summary JSON.")

            self.send_to_server(
                1,
                json.dumps(summary, ensure_ascii=False, indent=2)
            )

        finally:
            self.mark_stopped()

    def stop(self, notify=True):
        self.request_stop(notify=notify)