SCRIPT_METADATA = {
    "name": "mac/recon/get_installed_apps",
    "display_name": "List Installed Apps",
    "description": "Get installed applications on macOS",
    "platforms": ["darwin"],
    "category": "Gather",
    "params": []
}


import subprocess
import json
from pathlib import Path


def get_installed_apps():
    """获取系统中已安装的应用程序"""
    apps = []
    search_paths = [
        "/Applications",
        "/System/Applications",
        str(Path.home() / "Applications")
    ]

    for path in search_paths:
        p = Path(path)
        if p.exists():
            for app in p.glob("*.app"):
                info_plist = app / "Contents" / "Info.plist"
                app_info = {
                    "name": app.stem,
                    "path": str(app),
                    "location": path,
                    "bundle_id": '',
                    "version": ''
                }

                # 尝试读取Info.plist获取更多信息
                if info_plist.exists():
                    try:
                        result = subprocess.run(
                            ['plutil', '-convert', 'json', '-o', '-', str(info_plist)],
                            capture_output=True, text=True
                        )
                        if result.returncode == 0:
                            import json as json_module
                            plist_data = json_module.loads(result.stdout)
                            app_info["bundle_id"] = plist_data.get("CFBundleIdentifier", "")
                            app_info["version"] = plist_data.get("CFBundleShortVersionString", "")
                    except:
                        pass

                apps.append(app_info)

    # 去重
    seen = set()
    unique_apps = []
    for app in apps:
        if app["name"] not in seen:
            seen.add(app["name"])
            unique_apps.append(app)

    return unique_apps


print(json.dumps(get_installed_apps(), indent=2, ensure_ascii=False))