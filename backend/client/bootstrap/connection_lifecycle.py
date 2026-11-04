import json
import threading
import time

from client.connection.server_connection import ServerConnection
from client.connection.transport_connectors import get_connector
from client.config.config import RUNTIME_CONFIG
from client.runtime.client_info_builder import ClientInfoBuilder
from core.protocol.message_types import MSG_TYPE_UPDATE_REGISTRATION_ACK
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

    @property
    def is_paused(self):
        return not self._active.is_set()

    def pause(self):
        """Disconnect this instance and inhibit automatic reconnect attempts."""
        self._active.clear()
        self.reset_connection()
        logger.info('Client main connection paused')

    def resume(self):
        """Re-enable the existing connection loop without replacing this process."""
        self._active.set()

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

    def connect_socket(self):
        """Connect and optionally verify the server's pinned TLS certificate."""
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
        update_probe = str(getattr(self.client, 'update_registration_probe', '') or '')
        if update_probe:
            info['update_registration_probe'] = update_probe
        self.client.info = info
        handshake_json = json.dumps(info, ensure_ascii=False, indent=2)
        logger.info('Client handshake info:\n%s', handshake_json)
        self.client.server.send(info)
        if update_probe:
            # The update candidate must receive proof that Server registered it,
            # not just that its local socket accepted an info frame.
            sock = self.client.server.socket
            previous_timeout = sock.gettimeout()
            try:
                sock.settimeout(8)
                receipt = self.client.server.recv()
            finally:
                sock.settimeout(previous_timeout)
            if (receipt.get('type') != MSG_TYPE_UPDATE_REGISTRATION_ACK
                    or receipt.get('probe') != update_probe
                    or receipt.get('client_id') != self.client.client_id):
                raise RuntimeError('Update candidate was not confirmed by Server')
            self.client.update_server_registered = True
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
