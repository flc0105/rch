import json
import threading
import time

from client.connection.server_connection import ServerConnection
from client.connection.transport_connectors import get_connector
from client.config.config import RUNTIME_CONFIG
from client.connection.handshake import ClientInfoBuilder
from core.utils.logger import logger


class ClientConnectionLifecycle:
    """
    客户端连接生命周期管理。

    负责：
    - 创建 ServerConnection
    - 建立 socket 连接
    - 发送握手信息
    - 连接断开后的运行态清理和连接对象重建
    """

    def __init__(self, client):
        self.client = client
        self._active = threading.Event()
        self._active.set()
        self._bind_listener = None

    @property
    def is_bind_mode(self):
        return str(RUNTIME_CONFIG.get('connection_mode') or 'reverse').strip() == 'bind'

    @property
    def is_paused(self):
        return not self._active.is_set()

    def pause(self):
        """Disconnect this instance and inhibit automatic reconnect attempts."""
        self._active.clear()
        if self._bind_listener is not None:
            self._bind_listener.set_accepting(False)
        self.reset_connection()
        logger.info('Client main connection paused')

    def resume(self):
        """Re-enable the existing connection loop without replacing this process."""
        self._active.set()
        if self._bind_listener is not None:
            self._bind_listener.set_accepting(True)

    def wait_until_active(self):
        self._active.wait()

    def create_connection(self):
        """
        创建一个新的服务端连接对象
        """
        server = ServerConnection(features=getattr(self.client, 'features', None))
        server.client_id = self.client.client_id
        server.watchdog_manager = self.client.watchdog_manager
        server.process_recovery_watchdog_manager = self.client.process_recovery_watchdog_manager
        return server

    def close_current_connection(self):
        """
        关闭当前连接
        """
        try:
            self.client.server.shutdown()
        except OSError:
            pass
        try:
            self.client.server.close()
        except OSError:
            pass

    def reset_connection(self):
        """
        关闭当前连接并重建连接对象
        """
        self.client.receiver_worker.stop()
        self.close_current_connection()
        if not self.client.receiver_worker.join():
            logger.warning('Previous ClientReceiver did not exit after connection shutdown')
        self.handle_connection_lost()
        self.client.receiver_worker.reset_runtime()
        self.client.server = self.create_connection()
        if self._bind_listener is not None:
            self._bind_listener.release_session()

    def close_bind_listener(self):
        if self._bind_listener is not None:
            self._bind_listener.close()
            self._bind_listener = None

    def connect_socket(self):
        """Connect reverse mode or accept one Bind TCP session."""
        mode = str(RUNTIME_CONFIG.get('connection_mode') or 'reverse').strip()
        if mode == 'bind':
            if self._bind_listener is None:
                from client.connection.bind_listener import BindListener
                self._bind_listener = BindListener(RUNTIME_CONFIG)
                self._bind_listener.start()
            self.client.server.adopt_socket(self._bind_listener.accept())
            return
        if mode != 'reverse':
            raise ValueError('connection_mode must be reverse or bind')
        protocol = str(RUNTIME_CONFIG.get('server_transport') or 'tcp').strip()
        connector = get_connector(protocol)
        connector.validate(RUNTIME_CONFIG)
        logger.info('Connecting to %s via %s', self.client.address, protocol)
        while True:
            try:
                if connector.connect(self.client.server, self.client.address, RUNTIME_CONFIG):
                    return
            except OSError as exc:
                logger.warning('Connection attempt failed: %s', exc)
            self.client.server.close()
            time.sleep(self.client.RECONNECT_INTERVAL)
            print('Attempting to reconnect...')
            self.client.server = self.create_connection()

    def handshake(self):
        """
        连接建立后发送客户端握手信息
        """
        info = ClientInfoBuilder(
            client_id=self.client.client_id,
            command_executor=self.client.server.runtime.command_executor,
            features=self.client.server.runtime.features,
        ).build()
        if self.client.recovery_source:
            info['recovery_source'] = self.client.recovery_source
        self.client.info = info
        handshake_json = json.dumps(info, ensure_ascii=False, indent=2)
        logger.info('Client handshake info:\n%s', handshake_json)
        self.client.server.send(info)
        self.client.server.mark_connected()
        # The source describes only the first successful startup handshake.
        self.client.recovery_source = ''
        logger.info('Connected')

    def handle_connection_lost(self):
        """
        连接断开时的统一清理逻辑：
        - 先标记连接失效
        - 停掉所有后台任务
        - 清掉旧连接运行态
        """
        try:
            self.client.server.mark_disconnected()
        except Exception:
            pass

        try:
            stopped_jobs = self.client.server.runtime.handle_connection_lost()
            if stopped_jobs:
                logger.info(f'Stopped background jobs after connection loss: {stopped_jobs}')
        except Exception as e:
            logger.error(f'Failed to stop background jobs after connection loss: {e}', exc_info=True)

        try:
            self.client.server.reset_runtime_state()
        except Exception as e:
            logger.error(f'Failed to reset runtime state after connection loss: {e}', exc_info=True)
