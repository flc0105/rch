from server.application.assembly import ServerApplicationAssembly


class ServerWebService:
    """
    Server 的 Web 根外观（root facade）。

    职责：
    - 暴露装配完成的子外观对象
    - 暴露少量共享基础设施引用
    - 不再承载大批具体业务方法

    约束：
    - 不保留旧的 command/job/artifact/remote-file/agent/connection 转发方法
    - 不再直接暴露底层 service / factory 作为旧入口
    - 路由层和外部调用方必须显式迁移到子外观
    """

    def __init__(self, server, assembly=None):
        self.server = server
        self.assembly = assembly or ServerApplicationAssembly(server)

        # ------------------ shared infrastructure ------------------ #
        self.event_bus = self.assembly.event_bus
        self.script_grant_service = self.assembly.script_grant_service

        # ------------------ sub facades / apis ------------------ #
        self.connection_api = self.assembly.connection_api
        self.toolbar_preferences_api = self.assembly.toolbar_preferences_api
        self.notification_preferences_api = self.assembly.notification_preferences_api
        self.notification_history_api = self.assembly.notification_history_api
        self.server_cleanup_api = self.assembly.server_cleanup_api
        self.command_catalog_api = self.assembly.command_catalog_api
        self.command_execution_api = self.assembly.command_execution_api
        self.quick_action_api = self.assembly.quick_action_api
        self.command_history_api = self.assembly.command_history_api
        self.device_event_api = self.assembly.device_event_api
        self.external_tool_api = self.assembly.external_tool_api
        self.job_api = self.assembly.job_api
        self.script_api = self.assembly.script_api
        self.artifact_api = self.assembly.artifact_api
        self.remote_file_api = self.assembly.remote_file_api
        self.pinned_path_api = self.assembly.pinned_path_api
        self.keychain_api = self.assembly.keychain_api
        self.agent_api = self.assembly.agent_api
        self.process_control_api = self.assembly.process_control_api
        self.terminal_api = self.assembly.terminal_api
        self.screen_view_api = self.assembly.screen_view_api
        self.clipboard_api = self.assembly.clipboard_api
        self.device_monitor_api = self.assembly.device_monitor_api
        self.transfer_api = self.assembly.transfer_api

    @classmethod
    def from_server(cls, server):
        """
        默认构建入口：
        - 先完成 application assembly
        - 再创建 facade
        """
        assembly = ServerApplicationAssembly(server)
        return cls(server, assembly=assembly)
