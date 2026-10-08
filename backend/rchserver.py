import threading

from core.protocol.rchsocket import RCHSocket
from server.application.app_facade import ServerWebService
from server.application.command.alias_manager import AliasManager
from server.application.history.history_orchestrator import CommandHistoryOrchestrator
from server.application.history.history_store import CommandHistoryStore
from server.config.config import RCH_DB_PATH, SOCKET_ADDR
from server.persistence.rch_database import RchDatabase
from server.connection.client_session import ClientSession
from server.connection.connection_manager import ConnectionManager
from server.runtime.command_shell import ServerCommandShell
from server.runtime.server_heartbeat_runner import ServerHeartbeatRunner
from server.runtime.server_listener import ServerListener


class Server:

    def __init__(self, address):
        """
        初始化服务器对象
        :param address: 服务器地址
        """
        self.address = address
        self.socket = RCHSocket()
        self.connections = ConnectionManager()
        self.alias_manager = AliasManager()
        self.database = RchDatabase(RCH_DB_PATH)
        self.command_history = CommandHistoryStore(self.database)
        self.command_history_orchestrator = CommandHistoryOrchestrator(self.command_history)

        # composition root:
        # 由 Server 负责触发应用层装配，再拿到 Facade。
        self.web_service = ServerWebService.from_server(self)

        self.listener = ServerListener(self)
        self.heartbeat_runner = ServerHeartbeatRunner(self)
        self.command_shell = ServerCommandShell(self)

    # ------------------ connection lookup ------------------ #
    def get_target_connection_by_client_id(self, client_id) -> ClientSession:
        try:
            return self.connections.get_by_client_id(client_id)
        except Exception:
            raise Exception('Not a valid selection')

    def kill_connection_by_client_id(self, client_id):
        session = self.get_target_connection_by_client_id(client_id)
        session.send_command('kill_connection')

    # ------------------ runtime delegates ------------------ #
    def serve(self):
        """
        接受新连接的线程
        """
        return self.listener.serve()

    def heartbeat_loop(self):
        """
        周期性向所有在线 session 发送 heartbeat。
        """
        return self.heartbeat_runner.run()

    def schedule_startup_cleanup(self):
        return self.web_service.server_cleanup_api.schedule_startup_cleanup()


if __name__ == "__main__":
    server = Server(SOCKET_ADDR)

    heartbeat_thread = threading.Thread(target=server.heartbeat_loop)
    heartbeat_thread.daemon = True
    heartbeat_thread.start()

    server_thread = threading.Thread(target=server.serve)
    server_thread.daemon = True
    server_thread.start()

    server.schedule_startup_cleanup()
    server.command_shell.serve_console_loop()
