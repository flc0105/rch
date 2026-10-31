import queue
import socket
import time
import uuid

from client.bootstrap.connection_lifecycle import ClientConnectionLifecycle
from client.bootstrap.receiver_worker import ClientReceiverWorker
from client.config.runtime_config import RECONNECT_INTERVAL_SECONDS
from client.config.runtime_config_reporter import log_runtime_config_overrides_if_any
from client.config.feature_config import resolve_features
from client.watchdog.recovery_source import consume_recovery_source
from core.utils.logger import logger


class Client:
    RECONNECT_INTERVAL = RECONNECT_INTERVAL_SECONDS
    # Server heartbeat is sent every 30 seconds; allow four missed intervals.
    RECEIVE_IDLE_TIMEOUT_SECONDS = 120

    def __init__(self, address, process_recovery_watchdog_manager=None):
        self.address = address
        self.client_id = str(uuid.uuid4())
        self.server = None
        self.info = None
        self.process_recovery_watchdog_manager = process_recovery_watchdog_manager
        self.recovery_source = consume_recovery_source()

        self.receiver_worker = ClientReceiverWorker()
        self.features = resolve_features()
        self.watchdog_manager = None
        if self.features['watchdog']:
            from client.watchdog.client_watchdog_manager import ClientWatchdogManager
            self.watchdog_manager = ClientWatchdogManager(client_id=self.client_id)
        self.connection_lifecycle = ClientConnectionLifecycle(self)

        log_runtime_config_overrides_if_any()

        self.server = self.connection_lifecycle.create_connection()
        if self.watchdog_manager is not None:
            self.watchdog_manager.start()

    def connect(self):
        """
        建立连接并完成握手
        """
        if self.watchdog_manager is not None:
            self.watchdog_manager.start()
        self.connection_lifecycle.connect_socket()
        self.connection_lifecycle.handshake()
        self.receiver_worker.start(self.server)

    def _recover_from_connection_error(self, error):
        """
        连接异常后的恢复逻辑
        """
        logger.error(error, exc_info=True)
        while True:
            try:
                self.connection_lifecycle.reset_connection()
                self.connect()
                return
            except Exception as reconnect_error:
                logger.error('Client reconnection failed: %s', reconnect_error, exc_info=True)
                time.sleep(self.RECONNECT_INTERVAL)

    def wait(self):
        while True:
            try:
                receiver_error = self.receiver_worker.pop_error()
                if receiver_error is not None:
                    raise receiver_error

                idle = self.receiver_worker.receive_idle_seconds()
                if idle is not None and idle >= self.RECEIVE_IDLE_TIMEOUT_SECONDS:
                    raise TimeoutError(
                        f'Server inbound message timeout: no message for {idle:.1f}s'
                    )

                result = self.server.recv_command(timeout=0.5)
                if result:
                    self.server.send_result(*result)
            except queue.Empty:
                continue
            except SystemExit:
                logger.info('Server closed this connection')
                break
            except socket.error as e:
                self._recover_from_connection_error(e)
            except Exception as e:
                self._recover_from_connection_error(e)
