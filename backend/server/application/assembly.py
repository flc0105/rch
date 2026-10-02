from server.application.agent.agent_bootstrap_script_service import AgentBootstrapScriptService
from server.application.agent.agent_builder import AgentBuilder
from server.application.agent.agent_output_registry import AgentOutputRegistry
from server.application.auth.script_grant_service import ScriptGrantService
from server.application.artifact.artifact_service import WebArtifactService
from server.application.artifact.remote_file_service import WebRemoteFileService
from server.application.command.command_executor_factory import CommandExecutorFactory
from server.application.completion.command_completion_service import ServerCommandCompletionService
from server.application.connection.connection_history_store import ConnectionHistoryStore
from server.application.connection.connection_service import WebConnectionService
from server.application.connection.recent_device_store import RecentDeviceStore
from server.application.connection.device_group_store import DeviceGroupStore
from server.application.execution.remote_execution_service import RemoteExecutionService
from server.application.device_events.device_event_service import DeviceEventService
from server.application.external_tools.external_tool_catalog_service import ExternalToolCatalogService
from server.application.external_tools.external_tool_runtime_service import ExternalToolRuntimeService
from server.application.external_tools.external_tool_param_preset_store import ExternalToolParamPresetStore
from server.application.jobs.background_job_service import BackgroundJobService
from server.application.jobs.background_job_store import BackgroundJobStore
from server.application.jobs.job_catalog_service import JobCatalogService
from server.application.maintenance.server_cleanup_service import ServerCleanupService
from server.application.keychains.keychain_store import KeychainStore
from server.application.pinned_paths.pinned_path_store import PinnedPathStore
from server.application.preferences.toolbar_preference_store import ToolbarPreferenceStore
from server.application.preferences.notification_preference_store import NotificationPreferenceStore
from server.application.preferences.notification_history_store import NotificationHistoryStore
from server.application.preferences.notification_event_projector import NotificationEventProjector
from server.application.scripts.script_catalog_service import ScriptCatalogService
from server.application.tasks.task_runner import WebTaskRunner
from server.application.tasks.task_service import WebTaskService
from server.application.tasks.task_store import WebTaskStore
from server.application.terminal.pty_session_service import PtySessionService
from server.application.screen.screen_view_session_service import ScreenViewSessionService
from server.application.clipboard.clipboard_session_service import ClipboardSessionService
from server.application.monitor.device_monitor_session_service import DeviceMonitorSessionService
from server.application.transfers.transfer_service import TransferService
from server.application.web.agent_api import WebAgentApi
from server.application.web.artifact_api import WebArtifactApi
from server.application.web.command_catalog_api import WebCommandCatalogApi
from server.application.web.command_execution_api import WebCommandExecutionApi
from server.application.web.command_history_api import WebCommandHistoryApi
from server.application.web.device_event_api import WebDeviceEventApi
from server.application.web.external_tool_api import WebExternalToolApi
from server.application.web.connection_api import WebConnectionApi
from server.application.web.job_api import WebJobApi
from server.application.web.keychain_api import WebKeychainApi
from server.application.web.pinned_path_api import PinnedPathApi
from server.application.web.remote_file_api import WebRemoteFileApi
from server.application.web.quick_action_api import WebQuickActionApi
from server.application.web.script_api import WebScriptApi
from server.application.web.process_control_api import WebProcessControlApi
from server.application.web.terminal_api import WebTerminalApi
from server.application.web.toolbar_preferences_api import WebToolbarPreferencesApi
from server.application.web.notification_preferences_api import WebNotificationPreferencesApi
from server.application.web.notification_history_api import WebNotificationHistoryApi
from server.application.web.screen_view_api import WebScreenViewApi
from server.application.web.server_cleanup_api import WebServerCleanupApi
from server.application.web.clipboard_api import WebClipboardApi
from server.application.web.device_monitor_api import WebDeviceMonitorApi
from server.application.web.transfer_api import WebTransferApi
from server.config.config import (
    EXTERNAL_TOOL_META_PATH,
    EXTERNAL_TOOL_PACKAGE_PATH,
    SERVER_CLEANUP_ITEMS,
    SERVER_CLEANUP_LOG_ROOT_DIR,
    SERVER_CLEANUP_START_DELAY_SECONDS,
    SCRIPT_JOBS_PATH,
    SCRIPT_PATH,
)
from server.web.event_bus import WebEventBus


class ServerApplicationAssembly:
    """
    Server 应用装配层。

    职责：
    - 统一实例化应用层依赖
    - 统一处理跨 service/store 的依赖绑定
    - 统一装配 Web 子外观对象
    - 为 root facade 提供已经组装完成的依赖对象

    说明：
    - 这里不承载具体业务逻辑
    - 这里只负责“怎么创建”和“怎么接线”
    """

    def __init__(self, server):
        self.server = server

        # ------------------ shared infrastructure ------------------ #
        self.event_bus = WebEventBus()
        self.device_event_service = DeviceEventService(
            server=self.server,
            event_bus=self.event_bus,
        )
        self.task_store = WebTaskStore()
        self.transfer_service = TransferService(self.event_bus)

        # ------------------ domain/application services ------------------ #
        self.artifact_service = WebArtifactService()
        self.file_service = self.artifact_service
        self.script_grant_service = ScriptGrantService()

        self.remote_execution_service = RemoteExecutionService(
            self.server,
            artifact_service=self.artifact_service,
            transfer_service=self.transfer_service,
        )
        self.command_executor_factory = CommandExecutorFactory(
            server=self.server,
            remote_execution_service=self.remote_execution_service,
        )

        self.remote_file_service = WebRemoteFileService(
            remote_execution_service=self.remote_execution_service,
            artifact_service=self.artifact_service,
            transfer_service=self.transfer_service,
        )

        self.recent_device_store = RecentDeviceStore(self.server.database)
        self.device_group_store = DeviceGroupStore(self.server.database)
        self.toolbar_preference_store = ToolbarPreferenceStore(self.server.database)
        self.notification_preference_store = NotificationPreferenceStore(self.server.database)
        self.notification_history_store = NotificationHistoryStore(self.server.database)
        self.notification_event_projector = NotificationEventProjector(
            history_store=self.notification_history_store,
            server=self.server,
        )
        self.event_bus.set_notification_recorder(self.notification_event_projector.record_event)
        self.connection_history_store = ConnectionHistoryStore(self.server.database)

        self.connection_service = WebConnectionService(
            server=self.server,
            event_bus=self.event_bus,
            artifact_service=self.artifact_service,
            recent_device_store=self.recent_device_store,
            connection_history_store=self.connection_history_store,
            script_grant_service=self.script_grant_service,
        )

        self.task_runner = WebTaskRunner(
            server=self.server,
            event_bus=self.event_bus,
            task_store=self.task_store,
            remote_execution_service=self.remote_execution_service,
            command_executor_factory=self.command_executor_factory,
        )

        self.task_service = WebTaskService(
            server=self.server,
            task_store=self.task_store,
            file_service=self.file_service,
            task_runner=self.task_runner,
            transfer_service=self.transfer_service,
        )

        self.background_job_store = BackgroundJobStore(self.server.database)
        self.job_catalog_service = JobCatalogService(SCRIPT_JOBS_PATH)
        self.script_catalog_service = ScriptCatalogService(SCRIPT_PATH)
        self.external_tool_catalog_service = ExternalToolCatalogService(
            EXTERNAL_TOOL_META_PATH,
            EXTERNAL_TOOL_PACKAGE_PATH,
        )
        self.external_tool_param_preset_store = ExternalToolParamPresetStore(self.server.database)

        self.background_job_service = BackgroundJobService(
            event_bus=self.event_bus,
            job_store=self.background_job_store,
            remote_execution_service=self.remote_execution_service,
            job_catalog_service=self.job_catalog_service,
            server=self.server,
        )

        self.pinned_path_store = PinnedPathStore(self.server.database)
        self.keychain_store = KeychainStore()
        self.agent_builder = AgentBuilder()
        self.agent_output_registry = AgentOutputRegistry(self.agent_builder.output_dir)
        self.agent_bootstrap_script_service = AgentBootstrapScriptService()
        self.pty_session_service = PtySessionService(self.server, event_bus=self.event_bus)
        self.screen_view_session_service = ScreenViewSessionService(self.server, event_bus=self.event_bus)
        self.clipboard_session_service = ClipboardSessionService(self.server)
        self.device_monitor_session_service = DeviceMonitorSessionService(self.server, event_bus=self.event_bus)

        self.command_completion_service = ServerCommandCompletionService(
            server=self.server,
            remote_execution_service=self.remote_execution_service,
            pinned_path_store=self.pinned_path_store,
            external_tool_catalog_service=self.external_tool_catalog_service,
        )

        # ------------------ web sub facades / apis ------------------ #
        self.connection_api = WebConnectionApi(
            connection_service=self.connection_service,
            device_group_store=self.device_group_store,
        )

        self.toolbar_preferences_api = WebToolbarPreferencesApi(
            preference_store=self.toolbar_preference_store,
        )

        self.notification_preferences_api = WebNotificationPreferencesApi(
            preference_store=self.notification_preference_store,
            event_bus=self.event_bus,
        )

        self.notification_history_api = WebNotificationHistoryApi(
            history_store=self.notification_history_store,
            event_bus=self.event_bus,
        )

        self.server_cleanup_service = ServerCleanupService(
            event_bus=self.event_bus,
            notification_history_api=self.notification_history_api,
            artifact_service=self.artifact_service,
            agent_output_registry=self.agent_output_registry,
            cleanup_items=SERVER_CLEANUP_ITEMS,
            start_delay_seconds=SERVER_CLEANUP_START_DELAY_SECONDS,
            log_root_dir=SERVER_CLEANUP_LOG_ROOT_DIR,
        )
        self.server_cleanup_api = WebServerCleanupApi(self.server_cleanup_service)

        self.command_catalog_api = WebCommandCatalogApi(
            server=self.server,
            command_executor_factory=self.command_executor_factory,
            command_completion_service=self.command_completion_service,
        )

        self.command_execution_api = WebCommandExecutionApi(
            task_service=self.task_service,
            command_executor_factory=self.command_executor_factory,
            remote_execution_service=self.remote_execution_service,
        )

        self.quick_action_api = WebQuickActionApi(
            server=self.server,
            alias_manager=self.server.alias_manager,
            command_execution_api=self.command_execution_api,
        )

        self.external_tool_runtime_service = ExternalToolRuntimeService(
            catalog_service=self.external_tool_catalog_service,
            command_execution_api=self.command_execution_api,
            remote_execution_service=self.remote_execution_service,
            event_bus=self.event_bus,
        )

        self.external_tool_api = WebExternalToolApi(
            catalog_service=self.external_tool_catalog_service,
            runtime_service=self.external_tool_runtime_service,
            param_preset_store=self.external_tool_param_preset_store,
            server=self.server,
        )

        self.command_history_api = WebCommandHistoryApi(
            server=self.server,
        )

        self.device_event_api = WebDeviceEventApi(
            device_event_service=self.device_event_service,
        )

        self.job_api = WebJobApi(
            background_job_service=self.background_job_service,
            job_catalog_service=self.job_catalog_service,
        )

        self.script_api = WebScriptApi(
            command_execution_api=self.command_execution_api,
            script_catalog_service=self.script_catalog_service,
        )

        self.artifact_api = WebArtifactApi(
            server=self.server,
            event_bus=self.event_bus,
            artifact_service=self.artifact_service,
            command_execution_api=self.command_execution_api,
        )

        self.remote_file_api = WebRemoteFileApi(
            remote_file_service=self.remote_file_service,
        )

        self.pinned_path_api = PinnedPathApi(
            server=self.server,
            pinned_path_store=self.pinned_path_store,
        )

        self.keychain_api = WebKeychainApi(
            server=self.server,
            keychain_store=self.keychain_store,
            connection_service=self.connection_service,
        )

        self.agent_api = WebAgentApi(
            agent_builder=self.agent_builder,
            agent_output_registry=self.agent_output_registry,
            bootstrap_script_service=self.agent_bootstrap_script_service,
            event_bus=self.event_bus,
        )

        self.process_control_api = WebProcessControlApi(
            server=self.server,
            remote_execution_service=self.remote_execution_service,
        )

        self.terminal_api = WebTerminalApi(
            pty_session_service=self.pty_session_service,
        )

        self.screen_view_api = WebScreenViewApi(
            screen_view_session_service=self.screen_view_session_service,
        )

        self.clipboard_api = WebClipboardApi(
            clipboard_session_service=self.clipboard_session_service,
            artifact_service=self.artifact_service,
        )

        self.device_monitor_api = WebDeviceMonitorApi(
            device_monitor_session_service=self.device_monitor_session_service,
        )

        self.transfer_api = WebTransferApi(
            transfer_service=self.transfer_service,
            server=self.server,
        )

        self._wire_cross_dependencies()

    def _wire_cross_dependencies(self):
        """
        统一处理跨对象依赖绑定。

        这类 wiring 原本散落在 Facade 中，
        现在收口到 assembly，避免 Facade 同时承担装配职责。
        """
        self.background_job_store.artifact_service = self.artifact_service
        self.background_job_store.backfill_file_snapshots(self.artifact_service.list_artifacts())
        self.server.command_history.artifact_service = self.artifact_service