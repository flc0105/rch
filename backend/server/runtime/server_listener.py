import errno
import json
import socket
import threading
import time

from core.utils.logger import logger
from server.connection.transport.client_transport import ClientTransport


class ServerListener:
    _CLOSED_SOCKET_ERRNOS = {
        errno.EBADF,
        errno.EINVAL,
        getattr(errno, 'ENOTSOCK', 88),
        10038,  # Windows WSAENOTSOCK
    }

    def __init__(self, server):
        self.server = server
        self._stop_event = threading.Event()

    def stop(self):
        """
        停止监听。关闭 socket 用于唤醒阻塞中的 accept()。
        """
        self._stop_event.set()
        try:
            self.server.socket.shutdown()
        except OSError:
            pass
        finally:
            try:
                self.server.socket.close()
            except OSError:
                pass

    def _is_closed_socket_error(self, exc: OSError) -> bool:
        return getattr(exc, 'errno', None) in self._CLOSED_SOCKET_ERRNOS

    def _bind_server_socket(self):
        """
        绑定并启动监听
        """
        self.server.socket.bind(self.server.address)
        logger.info('Listening on port {}'.format(self.server.address[1]))

    def _receive_client_info(self, raw_sock, addr):
        """
        接收客户端初始信息
        """
        raw_sock.settimeout(5)
        try:
            transport = ClientTransport(raw_sock, addr)
            return transport.recv(), transport
        finally:
            raw_sock.settimeout(None)

    def _build_connection_info(self, addr, info: dict) -> dict:
        """
        构造客户端连接信息
        """
        return {**{'addr': f'{addr[0]}:{addr[1]}'}, **info}

    def _register_connection(self, transport: ClientTransport, addr, info: dict):
        session = self.server.web_service.connection_api.create_web_connection(transport, addr, info)
        self.server.connections.add(session)
        logger.info('Connection has been established: {}'.format(addr))
        self.server.web_service.connection_api.handle_connection_registered(session)
        return session

    def _accept_connection(self):
        """
        接受一个新连接并完成初始化
        """
        raw_sock, addr = self.server.socket.accept()

        try:
            info, transport = self._receive_client_info(raw_sock, addr)
        except json.JSONDecodeError:
            raw_sock.close()
            logger.error('Failed to establish session: invalid client handshake from {}'.format(addr))
            return None
        except Exception as e:
            raw_sock.close()
            logger.error('Error establishing connection: {}'.format(e))
            return None

        info = self._build_connection_info(addr, info)
        return self._register_connection(transport, addr, info)

    def _start_connection_handler(self, session):
        """
        启动客户端会话接收线程
        """
        threading.Thread(
            target=self.connection_handler,
            args=(session,),
            daemon=True
        ).start()

    def _notify_connection_closed(self, session):
        """
        通知等待中的主线程：该连接已关闭
        """
        session.runtime.message_queue.put(0, None, 1)

    def _remove_connection(self, session):
        """
        从连接管理器中移除连接
        """
        self.server.connections.remove(session)

    def _handle_connection_closed(self, session):
        """
        处理连接关闭后的清理逻辑

        关键点：
        - 不管 recent-device / event-bus / 其它副作用是否抛异常
        - 都必须保证连接最终从 ConnectionManager 中移除
        """
        client_id = getattr(getattr(session, 'session_info', None), 'client_id', '')
        logger.error(f'Connection closed: {session.address} client_id={client_id}')

        try:
            try:
                self.server.web_service.connection_api.handle_connection_closed(session)
            except Exception:
                logger.error(
                    'handle_connection_closed failed: addr=%s client_id=%s',
                    session.address,
                    client_id,
                    exc_info=True,
                )

            try:
                self._notify_connection_closed(session)
            except Exception:
                logger.error(
                    'notify_connection_closed failed: addr=%s client_id=%s',
                    session.address,
                    client_id,
                    exc_info=True,
                )
        finally:
            try:
                before_len = len(self.server.connections)
                logger.warning(
                    'Removing connection from manager: addr=%s client_id=%s size_before=%s',
                    session.address,
                    client_id,
                    before_len,
                )
                self._remove_connection(session)
                after_len = len(self.server.connections)
                logger.warning(
                    'Removed connection from manager: addr=%s client_id=%s size_after=%s',
                    session.address,
                    client_id,
                    after_len,
                )
            except Exception:
                logger.error(
                    'remove_connection failed: addr=%s client_id=%s',
                    session.address,
                    client_id,
                    exc_info=True,
                )

    def _handle_connection_receive_error(self, session):
        """
        处理接收线程中的非致命异常
        """
        logger.error(f'Error receiving from {session.address}', exc_info=True)
        time.sleep(1)

    def connection_handler(self, session):
        """
        处理接收的子线程
        """
        while 1:
            try:
                session.recv_message()
            except socket.error:
                self._handle_connection_closed(session)
                break
            except Exception:
                self._handle_connection_receive_error(session)

    def serve(self):
        """
        接受新连接的线程
        """
        try:
            self._bind_server_socket()
        except Exception as e:
            logger.error('Error binding socket: {}'.format(e))
            return

        while not self._stop_event.is_set():
            try:
                session = self._accept_connection()
                if session is None:
                    continue
                self._start_connection_handler(session)
            except OSError as e:
                if self._stop_event.is_set() or self._is_closed_socket_error(e):
                    return
                logger.error(e)
                # 避免持续性 accept 错误形成 CPU / 日志热循环。
                time.sleep(0.1)
