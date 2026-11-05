import queue
import socket
import time
import uuid

from client.bootstrap.connection_lifecycle import ClientConnectionLifecycle
from client.bootstrap.receiver_worker import ClientReceiverWorker
from client.config import runtime_config
from client.config.runtime_config_reporter import log_runtime_config_overrides_if_any
from client.config.feature_config import resolve_features
from client.watchdog.recovery_source import consume_recovery_source
from core.utils.logger import logger


class Client:
    @property
    def RECONNECT_INTERVAL(self):
        return getattr(self, '_reconnect_interval_override', runtime_config.RECONNECT_INTERVAL_SECONDS)

    @RECONNECT_INTERVAL.setter
    def RECONNECT_INTERVAL(self, interval):
        self._reconnect_interval_override = interval

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
        self.local_ipc = None
        ipc = None
        try:
            from client.runtime.local_ipc import LocalIpcServer
            ipc = LocalIpcServer()
            ipc.register('connection.resume', self.connection_lifecycle.resume)
            ipc.start()
            self.local_ipc = ipc
            if self.watchdog_manager is not None:
                self.watchdog_manager.local_ipc_environment = ipc.child_environment()
        except (ImportError, OSError, RuntimeError) as exc:
            if ipc is not None:
                ipc.stop()
            logger.warning('Local IPC unavailable: %s', exc)

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
            if self.connection_lifecycle.is_paused is True:
                return
            # A completed TCP connect can still fail immediately at the protocol
            # layer (for example, plaintext sent to a TLS endpoint). Throttle
            # every recovery attempt, not just failed socket connections.
            time.sleep(self.RECONNECT_INTERVAL)
            if self.connection_lifecycle.is_paused is True:
                return
            try:
                self.connection_lifecycle.reset_connection()
                self.connect()
                return
            except Exception as reconnect_error:
                logger.error('Client reconnection failed: %s', reconnect_error, exc_info=True)

    def wait(self):
        try:
            self._wait_for_commands()
        finally:
            if getattr(self, 'local_ipc', None) is not None:
                self.local_ipc.stop()

    def _wait_for_commands(self):
        while True:
            if (getattr(self, 'connection_lifecycle', None) is not None
                    and self.connection_lifecycle.is_paused):
                self.connection_lifecycle.wait_until_active()
                self.connect()
                continue
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
                    if self.server.consume_pause_request():
                        # Identify an intentional pause after the command result and
                        # before closing the socket; ordinary losses remain unchanged.
                        self.server.report_session_end('client_paused', command='pause_connection')
                        self.connection_lifecycle.pause()
                        # Even an early Resume during socket cleanup must reconnect.
                        self.connection_lifecycle.wait_until_active()
                        self.connect()
            except queue.Empty:
                continue
            except SystemExit:
                logger.info('Server closed this connection')
                break
            except socket.error as e:
                self._recover_from_connection_error(e)
            except Exception as e:
                self._recover_from_connection_error(e)
