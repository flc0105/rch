# server/scripts/jobs/example_monitor.py
# Example monitor that reports system info every 10 seconds

JOB_METADATA = {
    "name": "example_monitor",
    "display_name": "Example Monitor",
    "description": "Report a heartbeat message periodically",
    "platforms": ["darwin", "windows", "linux"],
    "params": [
        {
            "name": "interval_seconds",
            "type": "integer",
            "required": False,
            "default": 10,
            "min": 1,
            "description": "Heartbeat interval in seconds"
        }
    ],
    "execution": {
    "default": "subprocess",
    "allowed": ["subprocess"]
}

}

import platform
import time

from client.jobs.core.job import Job


class ExampleMonitor(Job):
    def __init__(self):
        super().__init__()
        self.interval = 10

    def on_context_bound(self):
        self.interval = int(self.get_job_param('interval_seconds', 10) or 10)

    def run(self):
        self.mark_running()
        self.send_to_server(1, f"Example monitor started on {platform.node()}")

        while not self.stop_event.is_set():
            self.send_to_server(1, f"Working... {time.strftime('%Y-%m-%d %H:%M:%S')}")
            time.sleep(self.interval)

        self.send_to_server(1, "Example monitor stopped")
        self.mark_stopped()

    def stop(self, notify=True):
        self.request_stop(notify=notify)



