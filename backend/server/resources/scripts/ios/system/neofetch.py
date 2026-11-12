SCRIPT_METADATA = {
    "name": "ios/system/neofetch",
    "display_name": "iOS Neofetch",
    "description": "Display detailed iOS device information in a stylish neofetch-like format",
    "platforms": ["ios"],
    "category": "System",
    "params": []
}


import os
import sys
import socket
import plistlib
import ctypes
import textwrap
import shutil

from objc_util import ObjCClass, ns, c

try:
    import console
except ImportError:
    console = None


# auto / side / stack
# 竖屏建议 auto;如果你想强制左右排版,改成 "side"
FORCE_LAYOUT = "side"

# 横屏左右排版总字符宽度。若横屏还折行,调小到 84 / 80。
SIDE_OUTPUT_COLUMNS = 140

# 竖屏上下排版字符宽度。
STACK_OUTPUT_COLUMNS = 42


THEME = {
    "logo":    (0.00, 0.38, 0.75),
    "title":   (0.55, 0.10, 0.70),
    "section": (0.55, 0.10, 0.70),
    "key":     (0.75, 0.28, 0.08),
    "value":   (0.08, 0.08, 0.08),
    "dim":     (0.55, 0.55, 0.55),
    "green":   (0.10, 0.65, 0.25),
    "yellow":  (0.95, 0.65, 0.10),
    "red":     (0.90, 0.15, 0.15),
    "cyan":    (0.00, 0.55, 0.70),
}


APPLE_LOGO = r"""
                    'c.
                 ,xNMM.
               .OMMMMo
               OMMM0,
     .;loddo:' loolloddol;.
   cKMMMMMMMMMMNWMMMMMMMMMM0:
 .KMMMMMMMMMMMMMMMMMMMMMMMWd.
 XMMMMMMMMMMMMMMMMMMMMMMMX.
;MMMMMMMMMMMMMMMMMMMMMMMM:
:MMMMMMMMMMMMMMMMMMMMMMMM:
.MMMMMMMMMMMMMMMMMMMMMMMMX.
 kMMMMMMMMMMMMMMMMMMMMMMMMWd.
 .XMMMMMMMMMMMMMMMMMMMMMMMMMMk
  .XMMMMMMMMMMMMMMMMMMMMMMMMK.
    kMMMMMMMMMMMMMMMMMMMMMMd
     ;KMMMMMMMWXXWMMMMMMMk.
       .cooc,.    .,coo:.
""".strip("\n").splitlines()


def set_color(name):
    if not console:
        return
    try:
        console.set_color(*THEME.get(name, THEME["value"]))
    except Exception:
        pass


def reset_color():
    if not console:
        return
    try:
        console.set_color()
    except Exception:
        try:
            console.set_color(*THEME["value"])
        except Exception:
            pass


def write(text, color="value", end=""):
    set_color(color)
    print(text, end=end)
    reset_color()


def writeln(text="", color="value"):
    write(text, color=color, end="\n")


def human_bytes(n):
    try:
        n = float(n)
    except Exception:
        return "unknown"

    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            if unit == "B":
                return "{} {}".format(int(n), unit)
            return "{:.1f} {}".format(n, unit)
        n /= 1024

    return "{:.1f} PB".format(n)


def human_duration(seconds):
    try:
        seconds = int(seconds)
    except Exception:
        return "unknown"

    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts = []

    if days:
        parts.append("{}d".format(days))
    if hours:
        parts.append("{}h".format(hours))
    if minutes:
        parts.append("{}m".format(minutes))
    if not parts:
        parts.append("{}s".format(secs))

    return " ".join(parts)


def percent_0_1(x):
    try:
        return "{:.0f}%".format(float(x) * 100)
    except Exception:
        return "unknown"


def safe(func, default="unknown"):
    try:
        value = func()
        if value is None:
            return default
        return value
    except Exception:
        return default


def read_info_plist():
    NSBundle = ObjCClass("NSBundle")
    bundle_path = str(NSBundle.mainBundle().bundlePath())
    plist_path = os.path.join(bundle_path, "Info.plist")

    with open(plist_path, "rb") as f:
        return plistlib.load(f)


def sysctl_string(name):
    try:
        sysctlbyname = c.sysctlbyname
        sysctlbyname.argtypes = [
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        sysctlbyname.restype = ctypes.c_int

        size = ctypes.c_size_t()

        if sysctlbyname(name.encode("utf-8"), None, ctypes.byref(size), None, 0) != 0:
            return "unknown"

        buf = ctypes.create_string_buffer(size.value)

        if sysctlbyname(name.encode("utf-8"), buf, ctypes.byref(size), None, 0) != 0:
            return "unknown"

        return buf.value.decode("utf-8", "replace")

    except Exception:
        return "unknown"


def get_route_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


def get_ipv4_interfaces():
    AF_INET = 2

    class Sockaddr(ctypes.Structure):
        _fields_ = [
            ("sa_len", ctypes.c_uint8),
            ("sa_family", ctypes.c_uint8),
            ("sa_data", ctypes.c_char * 14),
        ]

    class SockaddrIn(ctypes.Structure):
        _fields_ = [
            ("sin_len", ctypes.c_uint8),
            ("sin_family", ctypes.c_uint8),
            ("sin_port", ctypes.c_uint16),
            ("sin_addr", ctypes.c_ubyte * 4),
            ("sin_zero", ctypes.c_char * 8),
        ]

    class IfAddrs(ctypes.Structure):
        pass

    IfAddrs._fields_ = [
        ("ifa_next", ctypes.POINTER(IfAddrs)),
        ("ifa_name", ctypes.c_char_p),
        ("ifa_flags", ctypes.c_uint),
        ("ifa_addr", ctypes.POINTER(Sockaddr)),
        ("ifa_netmask", ctypes.POINTER(Sockaddr)),
        ("ifa_dstaddr", ctypes.POINTER(Sockaddr)),
        ("ifa_data", ctypes.c_void_p),
    ]

    getifaddrs = c.getifaddrs
    getifaddrs.argtypes = [ctypes.POINTER(ctypes.POINTER(IfAddrs))]
    getifaddrs.restype = ctypes.c_int

    freeifaddrs = c.freeifaddrs
    freeifaddrs.argtypes = [ctypes.POINTER(IfAddrs)]
    freeifaddrs.restype = None

    addrs = ctypes.POINTER(IfAddrs)()
    result = []

    if getifaddrs(ctypes.byref(addrs)) != 0:
        return result

    try:
        p = addrs

        while p:
            item = p.contents

            if item.ifa_addr:
                family = item.ifa_addr.contents.sa_family

                if family == AF_INET:
                    name = item.ifa_name.decode("utf-8", "replace")
                    sin = ctypes.cast(
                        item.ifa_addr,
                        ctypes.POINTER(SockaddrIn)
                    ).contents
                    ip = socket.inet_ntoa(bytes(sin.sin_addr))
                    result.append((name, ip))

            p = item.ifa_next

    finally:
        freeifaddrs(addrs)

    seen = set()
    clean = []

    for name, ip in result:
        key = (name, ip)
        if key not in seen:
            seen.add(key)
            clean.append((name, ip))

    return clean


def get_interfaces_text():
    items = get_ipv4_interfaces()

    if not items:
        return "unknown"

    preferred = []

    for name, ip in items:
        if name == "en0" or name.startswith("pdp_ip"):
            preferred.append((name, ip))

    if not preferred:
        preferred = items

    return ", ".join("{}={}".format(name, ip) for name, ip in preferred[:5])


def get_icloud_container_ids(info):
    containers = info.get("NSUbiquitousContainers", {})

    if isinstance(containers, dict):
        return list(containers.keys())

    return []


def get_icloud_path(info):
    NSFileManager = ObjCClass("NSFileManager")
    fm = NSFileManager.defaultManager()

    for cid in get_icloud_container_ids(info):
        try:
            url = fm.URLForUbiquityContainerIdentifier_(ns(cid))
            if url:
                return str(url.path())
        except Exception:
            pass

    try:
        url = fm.URLForUbiquityContainerIdentifier_(None)
        if url:
            return str(url.path())
    except Exception:
        pass

    return "unavailable"


def get_screen_info():
    UIScreen = ObjCClass("UIScreen")
    screen = UIScreen.mainScreen()

    scale = safe(lambda: float(screen.scale()))
    brightness = safe(lambda: percent_0_1(screen.brightness()))

    native = "unknown"
    points = "unknown"

    try:
        b = screen.bounds()
        points = "{:.0f}×{:.0f}pt".format(b.size.width, b.size.height)
    except Exception:
        pass

    try:
        if screen.respondsToSelector_("nativeBounds"):
            nb = screen.nativeBounds()
            native = "{:.0f}×{:.0f}px".format(nb.size.width, nb.size.height)
    except Exception:
        pass

    return "{}, {}, {}x, {}".format(native, points, scale, brightness)


def get_audio_info():
    try:
        AVAudioSession = ObjCClass("AVAudioSession")
        session = AVAudioSession.sharedInstance()

        parts = []

        sample_rate = safe(lambda: float(session.sampleRate()))
        input_latency = safe(lambda: float(session.inputLatency()))
        output_latency = safe(lambda: float(session.outputLatency()))

        if isinstance(sample_rate, float):
            parts.append("{:.0f} Hz".format(sample_rate))

        if isinstance(input_latency, float):
            parts.append("in {:.1f} ms".format(input_latency * 1000))

        if isinstance(output_latency, float):
            parts.append("out {:.1f} ms".format(output_latency * 1000))

        try:
            route = session.currentRoute()
            outs = route.outputs()
            names = []

            for i in range(outs.count()):
                port = outs.objectAtIndex_(i)
                names.append(str(port.portName()))

            if names:
                parts.append(", ".join(names))
        except Exception:
            pass

        return ", ".join(parts) if parts else "unknown"

    except Exception:
        return "unknown"


def get_disk_info():
    try:
        usage = shutil.disk_usage(os.path.expanduser("~/Documents"))
        return "{} free / {} total".format(
            human_bytes(usage.free),
            human_bytes(usage.total)
        )
    except Exception:
        return "unknown"


def get_screen_width_points():
    try:
        UIScreen = ObjCClass("UIScreen")
        b = UIScreen.mainScreen().bounds()
        return float(b.size.width)
    except Exception:
        return 0


def should_use_side():
    if FORCE_LAYOUT == "side":
        return True

    if FORCE_LAYOUT == "stack":
        return False

    # 关键修复:
    # 只看当前实际宽度,不再用 max(width, height)。
    # iPhone 竖屏 width 大概 393,所以 stack。
    # iPhone 横屏 width 大概 852,所以 side。
    width = get_screen_width_points()

    return width >= 700


def shorten_middle(s, max_len):
    s = str(s)

    if max_len <= 0:
        return ""

    if len(s) <= max_len:
        return s

    if max_len <= 4:
        return s[:max_len]

    left = (max_len - 1) // 2
    right = max_len - 1 - left

    return s[:left] + "..." + s[-right:]


def shorten_path(path, max_len):
    return path
    # path = str(path)

    # home = os.path.expanduser("~")
    # if path.startswith(home):
    #     path = "~" + path[len(home):]

    # path = path.replace("/private/var/mobile", "~mobile")
    # path = path.replace("/Library/Mobile Documents/", "/Mobile Documents/")
    # path = path.replace("/Containers/Shared/AppGroup/", "/AppGroup/")

    # return shorten_middle(path, max_len)


def build_rows():
    info = read_info_plist()

    UIDevice = ObjCClass("UIDevice")
    NSProcessInfo = ObjCClass("NSProcessInfo")

    dev = UIDevice.currentDevice()
    proc = NSProcessInfo.processInfo()

    try:
        dev.setBatteryMonitoringEnabled_(True)
    except Exception:
        pass

    battery_state_map = {
        0: "unknown",
        1: "unplugged",
        2: "charging",
        3: "full",
    }

    thermal_map = {
        0: "nominal",
        1: "fair",
        2: "serious",
        3: "critical",
    }

    battery_level = safe(lambda: float(dev.batteryLevel()), -1)
    battery_state = safe(lambda: int(dev.batteryState()), 0)

    if isinstance(battery_level, float) and battery_level >= 0:
        battery = "{} ({})".format(
            percent_0_1(battery_level),
            battery_state_map.get(battery_state, "unknown")
        )
    else:
        battery = "unknown"

    thermal = "unknown"

    try:
        if proc.respondsToSelector_("thermalState"):
            t = int(proc.thermalState())
            thermal = thermal_map.get(t, "unknown({})".format(t))
    except Exception:
        pass

    app_name = info.get("CFBundleDisplayName") or info.get("CFBundleName") or "Pythonista"
    app_ver = "{} ({})".format(
        info.get("CFBundleShortVersionString", "unknown"),
        info.get("CFBundleVersion", "unknown")
    )

    return [
        ("section", "Device", ""),
        ("item", "Name", str(dev.name())),
        ("item", "Type", str(dev.model())),
        ("item", "Model", sysctl_string("hw.machine")),
        ("item", "OS", "{} {}".format(str(dev.systemName()), str(dev.systemVersion()))),

        ("blank", "", ""),

        ("section", "Hardware", ""),
        ("item", "CPU", "{} active / {} total".format(
            safe(lambda: int(proc.activeProcessorCount())),
            safe(lambda: int(proc.processorCount()))
        )),
        ("item", "Memory", human_bytes(safe(lambda: int(proc.physicalMemory()), 0))),
        ("item", "Disk", get_disk_info()),
        ("item", "Screen", get_screen_info()),
        ("item", "Battery", battery),
        ("item", "Power", "low power {}".format(
            "on" if safe(lambda: bool(proc.isLowPowerModeEnabled()), False) else "off"
        )),
        ("item", "Thermal", thermal),
        ("item", "Uptime", human_duration(safe(lambda: float(proc.systemUptime()), 0))),

        ("blank", "", ""),

        ("section", "Audio", ""),
        ("item", "Session", get_audio_info()),

        ("blank", "", ""),

        ("section", "Network", ""),
        ("item", "Route IP", get_route_ip()),
        ("item", "Interfaces", get_interfaces_text()),

        ("blank", "", ""),

        ("section", "iCloud", ""),
        ("item", "Container", get_icloud_path(info)),

        ("blank", "", ""),

        ("section", "Runtime", ""),
        ("item", "Host App", "{} {}".format(app_name, app_ver)),
        ("item", "Python", sys.version.split()[0]),
        ("item", "CWD", os.getcwd()),
    ]


def make_info_line(row, width, nowrap):
    kind, key, value = row

    if kind == "blank":
        return [""]

    if kind == "section":
        return [key]

    key_width = 10
    prefix = "{:<{}} ".format(key + ":", key_width)
    value_width = max(4, width - len(prefix))

    if key in ("Container", "CWD"):
        value = shorten_path(value, value_width)
    else:
        value = str(value)

    if nowrap:
        return [prefix + shorten_middle(value, value_width)]

    wrapped = textwrap.wrap(
        value,
        width=value_width,
        break_long_words=True,
        break_on_hyphens=False
    )

    if not wrapped:
        return [prefix]

    lines = [prefix + wrapped[0]]
    indent = " " * len(prefix)

    for part in wrapped[1:]:
        lines.append(indent + part)

    return lines


def build_info_lines(width, nowrap):
    lines = []

    for row in build_rows():
        for line in make_info_line(row, width, nowrap):
            lines.append((row[0], line))

    return lines


def print_info_line(kind, line):
    if line == "":
        print()
        return

    if kind == "section":
        writeln(line, "section")
        return

    if ":" in line:
        key, rest = line.split(":", 1)
        write(key + ":", "key")
        writeln(rest, "value")
    else:
        writeln(line, "value")


def print_palette():
    print()
    for name in ["red", "yellow", "green", "cyan", "logo", "section"]:
        write("● ", name)
    print()


def render_stack():
    for line in APPLE_LOGO:
        writeln(line, "logo")

    print()
    writeln("iPhone Fetch", "title")
    writeln("-" * 32, "dim")
    print()

    for kind, line in build_info_lines(STACK_OUTPUT_COLUMNS, nowrap=False):
        print_info_line(kind, line)

    print_palette()


def render_side():
    logo_width = max(len(line) for line in APPLE_LOGO)
    gap = 3

    total_width = SIDE_OUTPUT_COLUMNS
    info_width = max(20, total_width - logo_width - gap)

    info_lines = build_info_lines(info_width, nowrap=True)
    total_lines = max(len(APPLE_LOGO), len(info_lines))

    for i in range(total_lines):
        logo_line = APPLE_LOGO[i] if i < len(APPLE_LOGO) else ""
        row_kind, info_line = info_lines[i] if i < len(info_lines) else ("blank", "")

        write(logo_line.ljust(logo_width), "logo")
        write(" " * gap, "value")

        if info_line:
            print_info_line(row_kind, info_line)
        else:
            print()

    print_palette()


def main():
    if should_use_side():
        render_side()
    else:
        render_stack()


if __name__ == "__main__":
    main()
