
SCRIPT_METADATA = {
    "name": "test/client_abort",
    "display_name": "Client Crash Test",
    "description": "Intentionally crash the Client process.",
    "platforms": ["mac", "linux", "win"],
    "params": [],
}

import os

print(f"[CRASH TEST] Aborting PID: {os.getpid()}", flush=True)

# Trigger a real native process crash.
os.abort()