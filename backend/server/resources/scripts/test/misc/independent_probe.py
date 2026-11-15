SCRIPT_METADATA = {
    "name": "test/misc/independent_probe",
    "display_name": "Independent Probe",
    "platforms": ["*"],
    "execution": {
        "modes": {"allowed": ["inproc", "subprocess_pipe"], "default": "inproc"},
        "output": {"allowed": ["collect", "stream"], "default": "stream"},
    },
    "params": [],
}
import time
for i in range(1, 61):
    print(f"probe {i}", flush=True)
    time.sleep(1)
