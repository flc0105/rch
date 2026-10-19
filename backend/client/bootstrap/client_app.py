import queue
import socket
import uuid

from client.bootstrap.connection_lifecycle import ClientConnectionLifecycle
from client.bootstrap.receiver_worker import ClientReceiverWorker
from client.config.runtime_config import RECONNECT_INTERVAL_SECONDS
from client.config.runtime_config_reporter import log_runtime_config_overrides_if_any
from client.watchdog.client_guard_manager import ClientGuardManager
from client.watchdog.recovery_source import consume_recovery_source
from core.utils.logger import logger


class Client:
    RECONNECT_INTERVAL = RECONNECT_INTERVAL_SECONDS

    def __init__(self, address, process_watchdog_manager=None):
        self.address = address
        self.client_id = str(uuid.uuid4())
        self.server = None
        self.info = None
        self.process_watchdog_manager = process_watchdog_manager
        self.recovery_source = consume_recovery_source()

        self.receiver_worker = ClientReceiverWorker()
        self.guard_manager = ClientGuardManager(
            client_id=self.client_id,
        )
        self.connection_lifecycle = ClientConnectionLifecycle(self)

        log_runtime_config_overrides_if_any()

        self.server = self.connection_lifecycle.create_connection()
        self.guard_manager.start()

    def connect(self):
        """
        建立连接并完成握手
        """
        self.guard_manager.start()
        self.connection_lifecycle.connect_socket()
        self.connection_lifecycle.handshake()
        self.receiver_worker.start(self.server)

    def _recover_from_connection_error(self, error):
        """
        连接异常后的恢复逻辑
        """
        logger.error(error, exc_info=True)
        self.connection_lifecycle.reset_connection()
        self.connect()

    def wait(self):
        while True:
            try:
                receiver_error = self.receiver_worker.pop_error()
                if receiver_error is not None:
                    raise receiver_error

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
