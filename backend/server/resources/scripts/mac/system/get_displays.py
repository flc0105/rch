
#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "mac/system/get_displays",
    "display_name": "Displays",
    "description": "List connected displays and their graphics hardware.",
    "platforms": ["mac"],
    "category": "System",
    "params": []
}

import json
import subprocess


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
            or gpu.get("spdisplays_vram_shared")
            or gpu.get("spdisplays_vram_dynamic")
        )

        for display in gpu.get("spdisplays_ndrvs", []):
            displays.append({
                "name": display.get("_name"),
                "gpu": gpu.get("sppci_model"),
                "vendor": gpu.get("spdisplays_vendor"),
                "vram": gpu_vram,
                "type": display.get("spdisplays_display_type"),
                "resolution": display.get("_spdisplays_resolution"),
                "retina": display.get("spdisplays_retina") == "spdisplays_yes",
                "main": display.get("spdisplays_main") == "spdisplays_yes",
                "built_in": display.get("spdisplays_builtin") == "spdisplays_yes",
                "connection": display.get("spdisplays_connection_type"),
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

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()