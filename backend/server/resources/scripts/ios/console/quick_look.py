SCRIPT_METADATA = {
    "name": "ios/console/quick_look",
    "display_name": "Quick Look",
    "description": "Preview a file on your iOS device.",
    "platforms": ["ios"],
    "category": "Console",
    "params": [
        {
            "name": "file_path",
            "label": "File",
            "type": "remote_file",
            "required": True,
            "description": "Choose a file to preview."
        }
    ]
}

import os
import console

file_path = os.path.expanduser(str(kwargs['file_path']).strip())
if not os.path.isfile(file_path):
    raise FileNotFoundError('File not found: ' + file_path)
console.quicklook(file_path)
print('Preview opened: ' + file_path)
