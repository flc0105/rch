import time

from core.utils.logger import logger
from server.config.config import HEARTBEAT_INTERVAL_SECONDS


class ServerHeartbeatRunner:
    def __init__(self, server):
        self.server = server

    def run(self, stop_event=None):

        while stop_event is None or not stop_event.is_set():
            try:
                sessions = self.server.connections.all()
                for session in sessions:
                    try:
                        session.services.heartbeat_service.send_heartbeat()
                    except Exception as e:
                        logger.debug(f'Failed to send heartbeat to {session.address}: {e}')
            except Exception as e:
                logger.error(f'Heartbeat loop error: {e}', exc_info=True)

            if stop_event is None:
                time.sleep(HEARTBEAT_INTERVAL_SECONDS)
            else:
                stop_event.wait(HEARTBEAT_INTERVAL_SECONDS)