SCRIPT_METADATA = {
    "name": "ios/console/kill_app",
    "display_name": "Kill App",
    "description": "Quit Pythonista and disconnect the current client.",
    "platforms": ["ios"],
    "category": "Console",
    "params": []
}

import os
import time

time.sleep(0.2)
os._exit(0)
