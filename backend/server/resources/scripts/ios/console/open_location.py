SCRIPT_METADATA = {
    "name": "common/console/open_location",
    "display_name": "Open Location in Maps",
    "description": "Open a geographic location in Google Maps",
    "platforms": ["common"],
    "category": "Console",
    "params": [
        {
            "name": "latitude",
            "type": "number",
            "required": True,
            "default": "",
            "description": "Latitude coordinate"
        },
        {
            "name": "longitude",
            "type": "number",
            "required": True,
            "default": "",
            "description": "Longitude coordinate"
        }
    ]
}

import webbrowser
from client.runtime.client_util import require_kwarg

latitude = require_kwarg(kwargs, 'latitude')
longitude = require_kwarg(kwargs, 'longitude')

url = f'https://www.google.com/maps?q={latitude},{longitude}'
webbrowser.open(url)