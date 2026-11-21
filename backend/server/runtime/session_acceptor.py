"""Common post-accept lifecycle for all RCH TCP listeners."""
import errno
import json
import uuid
import socket
import threading
import time
import traceback

from core.utils.logger import logger
from server.connection.transport.client_transport import ClientTransport


class SessionAcceptor:
    def __init__(self, server):
        self.server = server

    def accept_session(self, raw_sock, addr, *, listener_id='', listener_name='', listener_port=None, protocol='tcp', strict_registration=False, raise_on_error=False):
        try:
            info, transport = self._receive_client_info(raw_sock, addr)
            if not isinstance(info, dict) or info.get('type') != 'info':
                raise ValueError('Invalid client info')
            if strict_registration:
                client_id = info.get('id')
                try:
                    if not isinstance(client_id, str) or str(uuid.UUID(client_id)) != client_id:
                        raise ValueError('Invalid Client ID')
                except (ValueError, TypeError, AttributeError):
                    raise ValueError('Invalid Client ID') from None
            info = self._build_connection_info(addr, info)
            session = self._register_connection(transport, addr, info,
                                                listener_id=listener_id,
                                                listener_name=listener_name, listener_port=listener_port,
                                                protocol=protocol, strict_registration=strict_registration)
            self._start_connection_handler(session)
            return session
        except Exception as exc:
            raw_sock.close()
            logger.error('Failed client handshake from %s: %s', addr, exc)
            if raise_on_error:
                raise
            return None

    def _receive_client_info(self, raw_sock, addr):
        """
        接收客户端初始信息
        """
        raw_sock.settimeout(5)
        try:
            transport = ClientTransport(raw_sock, addr)
            return transport.recv(max_bytes=8 * 1024 * 1024), transport
        finally:
            raw_sock.settimeout(None)

    def _build_connection_info(self, addr, info: dict) -> dict:
        """
        构造客户端连接信息
        """
        return {**{'addr': f'{addr[0]}:{addr[1]}'}, **info}

    def _register_connection(self, transport: ClientTransport, addr, info: dict, *, listener_id='', listener_name='', listener_port=None, protocol='tcp', strict_registration=False):
        session = self.server.web_service.connection_api.create_web_connection(transport, addr, info)
        session.listener_id = listener_id
        session.listener_name = listener_name
        session.listener_port = listener_port
        session.listener_protocol = protocol
        session.exclusive_registration = strict_registration
        if strict_registration:
            if not self.server.connections.add_if_absent(session):
                raise ValueError('Client ID already has an active session')
        else:
            self.server.connections.add(session)
        logger.info('Connection has been established: {}'.format(addr))
        try:
            if not self.server.connections.run_if_current(
                session, lambda: self.server.web_service.connection_api.handle_connection_registered(session)
            ):
                raise RuntimeError('Client session replaced before registration')
        except Exception:
            service = getattr(session.context, 'client_session_token_service', None)
            if service is not None:
                service.revoke(session)
            self.server.connections.remove(session)
            raise
        return session

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
        session.runtime.pending_results.close()

    def _remove_connection(self, session):
        """
        从连接管理器中移除连接
        """
        self.server.connections.remove(session)

    def _handle_connection_closed(self, session, error=None):
        """
        处理连接关闭后的清理逻辑

        关键点：
        - 不管 recent-device / event-bus / 其它副作用是否抛异常
        - 都必须保证连接最终从 ConnectionManager 中移除
        """
        client_id = getattr(getattr(session, 'session_info', None), 'client_id', '')
        if error is not None:
            if isinstance(error, (socket.timeout, TimeoutError)) or getattr(error, 'errno', None) == errno.ETIMEDOUT:
                reason = 'timeout'
            elif str(error) == 'Connection closed':
                reason = 'connection_lost'
            elif str(error) == 'Connection aborted':
                reason = 'unexpected_disconnect'
            else:
                reason = 'transport_error'
            diagnostics = {}
            if reason == 'unexpected_disconnect':
                diagnostics['summary'] = 'Protocol frame was interrupted'
            elif reason in ('transport_error', 'timeout'):
                diagnostics = {
                    'summary': f'{type(error).__name__}: {error}'[:500],
                    'traceback': traceback.format_exc()[-12000:],
                }
            session.context.transport_failure = {'reason': reason, 'detail': diagnostics}
        logger.error(f'Connection closed: {session.address} client_id={client_id}')

        try:
            try:
                api = self.server.web_service.connection_api
                current = self.server.connections.run_if_current(session, lambda: api.handle_connection_closed(session), allow_missing=True)
                if not current:
                    # Only session-scoped cleanup is safe for a replaced connection.
                    cleanup = getattr(api, 'handle_replaced_connection_closed', None)
                    if callable(cleanup):
                        cleanup(session)
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
            except socket.error as exc:
                self._handle_connection_closed(session, exc)
                break
            except Exception:
                self._handle_connection_receive_error(session)

