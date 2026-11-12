SCRIPT_METADATA = {
    "name": "ios/console/open_in",
    "display_name": "Open In",
    "description": "Share a file from your iOS device with another app.",
    "platforms": ["ios"],
    "category": "Console",
    "params": [
        {
            "name": "file_path",
            "label": "File",
            "type": "remote_file",
            "required": True,
            "description": "Choose a file on this device."
        }
    ]
}

import os
import console

file_path = os.path.expanduser(str(kwargs['file_path']).strip())
if not os.path.isfile(file_path):
    raise FileNotFoundError('File not found: ' + file_path)
console.open_in(file_path)
print('Open In launched: ' + file_path)
