SCRIPT_METADATA = {
    "name": "common/network/tcp_ping",
    "display_name": "TCP Ping",
    "description": "Measure TCP connection latency to a target host and port, similar to ICMP ping but over TCP",
    "platforms": ["common"],
    "category": "Network",
    "execution": {
    "modes": {'allowed': ['inproc', 'subprocess_pipe'], 'default': 'inproc'},
    "output": {'allowed': ['stream'], 'default': 'stream'},
    },
    "params": [
        {
            "name": "host",
            "type": "string",
            "required": False,
            "default": "baidu.com",
            "description": "Target hostname or IP address"
        },
        {
            "name": "port",
            "type": "number",
            "required": False,
            "default": 443,
            "description": "Target TCP port"
        },
        {
            "name": "count",
            "type": "number",
            "required": False,
            "default": 4,
            "description": "Number of connection attempts"
        },
    ]
}


import socket
import time


def tcp_ping(host, port=443, count=4, timeout=2.0):
    print("TCP ping {}:{} count={} timeout={}s".format(
        host, port, count, timeout
    ))

    try:
        infos = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except Exception as e:
        print("DNS failed:", repr(e))
        return

    addr = infos[0][4]
    print("resolved:", addr)

    times = []

    for i in range(count):
        s = socket.socket(infos[0][0], socket.SOCK_STREAM)
        s.settimeout(timeout)

        start = time.time()

        try:
            s.connect(addr)
            elapsed = (time.time() - start) * 1000.0
            times.append(elapsed)
            print("reply {}: {:.1f} ms".format(i + 1, elapsed))

        except Exception as e:
            print("timeout/error {}: {}".format(i + 1, repr(e)))

        finally:
            s.close()

        time.sleep(1)

    if times:
        print()
        print("min/avg/max = {:.1f}/{:.1f}/{:.1f} ms".format(
            min(times),
            sum(times) / len(times),
            max(times)
        ))


host = kwargs.get('host', 'baidu.com')
port = kwargs.get('port', '443')
count = kwargs.get('count', '4')
tcp_ping(host, port=int(port), count=int(count))

