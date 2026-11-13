from client.runtime.command_variable_resolver import CommandVariableResolver
from client.runtime.execution.runtime import ExecutionRuntime
from client.control_registration import build_control_dispatcher
from client.remote_files.manager import RemoteFilesManager
from client.scripts.manager import ScriptManager
from client.runtime.sdk.command import ScriptCommandAccess
from client.commands.runtime.executor import CommandExecutor
from client.jobs.core.manager import JobManager
from client.config.feature_config import resolve_features
from client.monitor.manager import DeviceMonitorManager
from client.transfers.manager import ClientTransferManager
from client.config.manager import ConfigurationManager
from client.watchdog.control import WatchdogControl
from client.process.manager import ProcessManager


class ClientRuntime:
    """
    Client 端运行时能力容器。

    只负责持有和协调客户端本地运行能力：
    - command_executor：shell-like / acmd 命令入口
    - control_dispatcher：结构化业务请求入口
    - execution：共享前台执行生命周期
    - remote_files_manager / script_manager：独立业务执行
    - job_manager：后台任务运行态
    - pty_manager：交互式 PTY 会话
    - screen_view_manager：只读屏幕预览会话
    - clipboard_manager：显式远程剪贴板桥接
    - device_monitor_manager：按需实时设备监控会话
    - transfer_manager：独立文件传输任务，不占 command foreground slot
    """

    def __init__(self, connection, features=None):
        self.connection = connection
        self.execution = ExecutionRuntime(connection)
        self.command_variable_resolver = CommandVariableResolver(connection)
        self.command_executor = CommandExecutor(connection, self.execution, self.command_variable_resolver)
        self.job_manager = JobManager(connection)
        self.remote_files_manager = RemoteFilesManager()
        self.script_manager = ScriptManager(ScriptCommandAccess(
            self.command_executor.sdk_command_names, self.command_executor.resolve_sdk_command,
        ))
        self.features = dict(features if features is not None else resolve_features())
        self.configuration_manager = ConfigurationManager(connection, self.features)
        self.process_manager = ProcessManager()
        self.watchdog_control = WatchdogControl(connection)
        self.pty_manager = None
        self.screen_view_manager = None
        self.clipboard_manager = None
        if self.features['pty']:
            from client.pty.manager import PtyManager
            self.pty_manager = PtyManager(connection)
        if self.features['screen_view']:
            from client.screen.manager import ScreenViewManager
            self.screen_view_manager = ScreenViewManager(connection)
        if self.features['clipboard']:
            from client.clipboard.manager import ClipboardManager
            self.clipboard_manager = ClipboardManager(connection)
        self.control_dispatcher = build_control_dispatcher(self)
        self.device_monitor_manager = DeviceMonitorManager(connection)
        self.transfer_manager = ClientTransferManager(connection)

    def handle_connection_lost(self) -> list[str]:
        """
        连接断开时清理依赖服务端连接的运行态。
        """
        self.control_dispatcher.disconnect()
        stopped_jobs = self.job_manager.handle_connection_lost()
        if self.pty_manager is not None:
            self.pty_manager.close_all_sessions(notify=False)
        if self.screen_view_manager is not None:
            self.screen_view_manager.close_all_sessions(notify=False)
        self.device_monitor_manager.close_all_sessions(notify=False)
        self.transfer_manager.cancel_all(notify=False)
        return stopped_jobs