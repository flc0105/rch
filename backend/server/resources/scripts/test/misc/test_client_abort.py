
SCRIPT_METADATA = {
    "name": "test/misc/test_client_abort",
    "display_name": "Test Client Crash",
    "description": "Intentionally crash the Client process.",
    "platforms": ["mac", "linux", "win"],
    "params": [],
}

import os

print(f"[CRASH TEST] Aborting PID: {os.getpid()}", flush=True)

# Trigger a real native process crash.
os.abort()