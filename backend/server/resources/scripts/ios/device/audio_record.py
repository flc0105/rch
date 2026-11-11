SCRIPT_METADATA = {
    "name": "ios/device/audio_record",
    "display_name": "Record Audio",
    "description": "Record audio from the device microphone and upload the recording to the server",
    "platforms": ["ios"],
    "category": "Device",
    "params": [
        {
            "name": "duration",
            "type": "number",
            "required": False,
            "default": 5,
            "description": "Recording duration in seconds"
        }
    ]
}

# coding: utf-8
import sound
import time
import os
import datetime
import console
import json

from client.config.config import UPLOAD_BASE_URL
from client.runtime.client_util import upload_file_via_http

UPLOAD_URL = UPLOAD_BASE_URL.rstrip('/') + '/api/files/upload'


def main():
    console.clear()

    duration = kwargs.get('duration', 5)

    filename = "recording_{}.m4a".format(
        datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    )

    path = os.path.join(os.path.expanduser("~/Documents"), filename)

    print("Recording {} seconds...".format(duration))
    print("File:", path)

    recorder = sound.Recorder(path)
    recorder.record(duration)

    # 等待录音结束
    while recorder.recording:
        print("time: {:.1f}s".format(recorder.current_time))
        time.sleep(0.5)

    print("Done.")
    print("Saved to:", path)

    ctx = kwargs.get('__context__', {})
    client_id = ctx.get('client_id', '')

    resp = upload_file_via_http(path, filename=filename, upload_url=UPLOAD_URL, category='inbox', client_id=client_id)

    try:
        payload = resp.json()
    except Exception:
        payload = resp.text

    print(json.dumps({
        'ok': bool(resp.ok),
        'status_code': int(resp.status_code),
        'filename': filename,
        'response': payload,
    }, ensure_ascii=False, indent=2))

main()