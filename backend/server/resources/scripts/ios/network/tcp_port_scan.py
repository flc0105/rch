SCRIPT_METADATA = {
    "name": "common/recon/tcp_port_scan",
    "display_name": "TCP Port Scan",
    "description": "Scan a list of TCP ports on a target host to check if they are open, closed, or filtered",
    "platforms": ["common"],
    "category": "Recon",
    "params": [
        {
            "name": "host",
            "type": "string",
            "required": False,
            "default": "baidu.com",
            "description": "Target hostname or IP address"
        },
        {
            "name": "ports",
            "type": "string",
            "required": False,
            "default": "22,80,443,8080,8443,9999",
            "description": "Comma-separated list of ports to scan"
        },
        {
            "name": "timeout",
            "type": "number",
            "required": False,
            "default": 1.0,
            "description": "Connection timeout in seconds per port"
        }
    ]
}

# coding: utf-8
import socket
import time


def scan_ports(host, ports, timeout=1.0):
    print("Scanning:", host)

    try:
        ip = socket.gethostbyname(host)
    except Exception as e:
        print("DNS error:", repr(e))
        return

    print("Resolved:", ip)
    print()

    for port in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)

        start = time.time()

        try:
            s.connect((ip, port))
            ms = (time.time() - start) * 1000
            print("{:5d} open     {:.1f} ms".format(port, ms))
        except socket.timeout:
            print("{:5d} filtered timeout".format(port))
        except ConnectionRefusedError:
            print("{:5d} closed   refused".format(port))
        except Exception as e:
            print("{:5d} error    {}".format(port, repr(e)))
        finally:
            s.close()


if __name__ == "__main__":
    host = kwargs.get('host', 'baidu.com')
    ports_str = kwargs.get('ports', '22,80,443,8080,8443,9999')
    timeout = kwargs.get('timeout', 1.0)

    ports = []
    for x in ports_str.split(','):
        x = x.strip()
        if x:
            ports.append(int(x))

    scan_ports(host, ports, timeout=timeout)