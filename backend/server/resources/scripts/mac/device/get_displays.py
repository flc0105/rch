
#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "mac/device/get_displays",
    "display_name": "Displays",
    "description": "List connected displays and their graphics hardware.",
    "platforms": ["mac"],
    "category": "Device",
    "params": []
}

import json
import subprocess

from client.runtime.sdk import context


def read_displays():
    result = subprocess.run(
        ["system_profiler", "SPDisplaysDataType", "-json"],
        capture_output=True,
        text=True,
        check=True,
    )

    data = json.loads(result.stdout)
    displays = []

    for gpu in data.get("SPDisplaysDataType", []):
        gpu_vram = (
            gpu.get("spdisplays_vram")
            or gpu.get("_spdisplays_vram")
            or gpu.get("spdisplays_vram_shared")
            or gpu.get("spdisplays_vram_dynamic")
        )

        for display in gpu.get("spdisplays_ndrvs", []):
            display_type = display.get("spdisplays_display_type") or ""
            connection = display.get("spdisplays_connection_type")
            pixel_resolution = display.get("spdisplays_pixelresolution") or ""
            displays.append({
                "name": display.get("_name"),
                "gpu": gpu.get("sppci_model"),
                "vendor": gpu.get("spdisplays_vendor"),
                "vram": gpu_vram,
                "type": display.get("spdisplays_display_type"),
                "resolution": display.get("_spdisplays_resolution"),
                "retina": (
                    display.get("spdisplays_retina") == "spdisplays_yes"
                    or "retina" in display_type.lower()
                    or "retina" in pixel_resolution.lower()
                ),
                "main": display.get("spdisplays_main") == "spdisplays_yes",
                "built_in": (
                    connection == "spdisplays_internal"
                    or display_type.startswith("spdisplays_built-in")
                ),
                "connection": connection,
                "online": display.get("spdisplays_online") == "spdisplays_yes",
            })

    return displays


def main():
    try:
        output = read_displays()
    except (
        OSError,
        subprocess.CalledProcessError,
        ValueError,
        TypeError
    ) as exc:
        output = {"error": f"Failed to read displays: {exc}"}

    context.emit(output)


if __name__ == "__main__":
    main()