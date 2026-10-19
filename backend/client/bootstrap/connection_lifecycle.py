import time

from client.connection.server_connection import ServerConnection
from client.runtime.client_info_builder import ClientInfoBuilder
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

    def create_connection(self):
        """
        创建一个新的服务端连接对象
        """
        server = ServerConnection()
        server.client_id = self.client.client_id
        server.guard_manager = self.client.guard_manager
        server.process_watchdog_manager = self.client.process_watchdog_manager
        return server

    def close_current_connection(self):
        """
        关闭当前连接
        """
        try:
            self.client.server.close()
        except Exception:
            pass

    def reset_connection(self):
        """
        关闭当前连接并重建连接对象
        """
        self.client.receiver_worker.stop()
        self.close_current_connection()
        self.handle_connection_lost()
        self.client.receiver_worker.reset_runtime()
        self.client.server = self.create_connection()

    def connect_socket(self):
        """
        建立到底层服务端的连接；失败时持续重试
        """
        logger.info(f'Connecting to {self.client.address}')

        while not self.client.server.connect(self.client.address):
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
        ).build()
        self.client.info = info
        self.client.server.send(info)
        self.client.server.mark_connected()
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
