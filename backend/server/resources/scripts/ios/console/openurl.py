SCRIPT_METADATA = {
    "name": "ios/console/openurl",
    "display_name": "Open URL",
    "description": "Open a link in the iOS browser or its associated app.",
    "platforms": ["ios"],
    "category": "Console",
    "params": [
        {
            "name": "url",
            "label": "URL",
            "type": "string",
            "required": True,
            "description": "Enter a URL to open."
        }
    ]
}

import webbrowser

url = str(kwargs['url']).strip()
if not url:
    raise ValueError('URL is required')
webbrowser.open(url)
