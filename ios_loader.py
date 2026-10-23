# ios_bootstrap_simple.py
# 完全独立:只依赖 requests + 标准库
# 作用:请求服务端构建 bundle -> 下载到 Documents/client_bundle/releases
#      -> 解压 -> 新线程 runpy 启动 ratclient.py -> 自己退出

import os
import sys
import time
import shutil
import zipfile
import runpy
import threading
from urllib.parse import urljoin

import requests


# ====== 改这里 ======

WEB_HOST = "192.168.2.47"
WEB_PORT = 8085
WEB_SCHEME = "http"

SERVER_HOST = WEB_HOST
SERVER_PORT = 9999

# ====================


BASE_URL = f"{WEB_SCHEME}://{WEB_HOST}:{WEB_PORT}"

RELEASE_DIR = os.path.join(
    os.path.expanduser("~"),
    "Documents",
    "client_bundle",
    "releases",
)


def log(msg):
    print(f"[bootstrap] {msg}")


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def build_bundle():
    url = urljoin(BASE_URL + "/", "/api/agent/build")

    payload = {
        "server_host": SERVER_HOST,
        "server_port": SERVER_PORT,
        "server_web_scheme": WEB_SCHEME,
        "server_web_host": WEB_HOST,
        "web_port": WEB_PORT,

        # 对齐 update 那套 bundle 构建规范
        "target_os": "bundle",
        "builder": "bundle",
        "target_arch": "",
        "source": "ios_bootstrap",
    }

    log(f"build request: {url}")
    r = requests.post(url, json=payload, timeout=300)
    r.raise_for_status()

    data = r.json()

    # 兼容你的 WebApiResponder:
    # {"code": 0, "message": "ok", "data": {...}}
    if isinstance(data, dict) and "code" in data:
        if data.get("code") != 0:
            raise RuntimeError(data.get("message") or data)
        return data.get("data") or {}

    return data


def download_file(download_url, save_path):
    log(f"download: {download_url}")
    r = requests.get(download_url, stream=True, timeout=300)
    r.raise_for_status()

    tmp_path = save_path + ".part"

    with open(tmp_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 64):
            if chunk:
                f.write(chunk)

    if os.path.exists(save_path):
        os.remove(save_path)

    os.rename(tmp_path, save_path)
    return save_path


def unzip(zip_path, extract_dir):
    if os.path.isdir(extract_dir):
        shutil.rmtree(extract_dir)

    os.makedirs(extract_dir, exist_ok=True)

    log(f"extract: {extract_dir}")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_dir)

    return extract_dir


def start_ratclient(bundle_dir):
    ratclient_path = os.path.join(bundle_dir, "rchclient.py")

    if not os.path.isfile(ratclient_path):
        raise FileNotFoundError(f"ratclient.py not found: {ratclient_path}")

    def runner():
        os.chdir(bundle_dir)

        if bundle_dir not in sys.path:
            sys.path.insert(0, bundle_dir)

        sys.argv = [ratclient_path]

        log(f"run: {ratclient_path}")
        runpy.run_path(ratclient_path, run_name="__main__")

    t = threading.Thread(target=runner, name="ratclient-main")
    t.daemon = False
    t.start()

    return t


def main():
    ensure_dir(RELEASE_DIR)

    result = build_bundle()

    download_url = result.get("download_url")
    if not download_url:
        raise RuntimeError(f"missing download_url: {result}")

    download_url = urljoin(BASE_URL + "/", download_url)

    file_name = result.get("file_name") or os.path.basename(download_url)
    zip_path = os.path.join(RELEASE_DIR, file_name)

    base_name = os.path.splitext(file_name)[0]
    extract_dir = os.path.join(RELEASE_DIR, base_name)

    download_file(download_url, zip_path)
    unzip(zip_path, extract_dir)

    start_ratclient(extract_dir)

    log("handoff done, bootstrap exits")
    time.sleep(0.2)
    sys.exit(0)


if __name__ == "__main__":
    main()