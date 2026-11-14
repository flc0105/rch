import { h } from 'vue';
import { ElNotification } from 'element-plus';
import {
    formatTerminalCommandFinishedLine,
    TERMINAL_BACKGROUND_PREFIX,
} from './terminalMarkers.js';
import { openWebEventStream } from '../api/streamApi.js';
import { loadNotificationPreferences } from '../api/notificationPreferencesApi.js';
import { loadTransfers } from '../api/transferApi.js';
import { loadNotificationHistory } from '../api/notificationHistoryApi.js';
import {
    DEFAULT_SSE_NOTIFICATION_PREFERENCES,
    cloneSseNotificationPreferences,
    normalizeSseNotificationPreferences,
} from '../data/sseNotificationPreferences.js';

export default {
    data() {
        return {
            tabId: '',
            eventSource: null,
            sseReady: false,
            sseNotificationPreferences: cloneSseNotificationPreferences(DEFAULT_SSE_NOTIFICATION_PREFERENCES),
            sseNotificationHistory: [],
            transferItems: [],
        }
    },


    methods: {
        async loadSseNotificationPreferences() {
            try {
                const preferences = await loadNotificationPreferences();
                this.applySseNotificationPreferences(preferences);
            } catch (e) {
                this.sseNotificationPreferences = cloneSseNotificationPreferences(DEFAULT_SSE_NOTIFICATION_PREFERENCES);
                console.warn('Failed to load SSE notification preferences; using defaults', e);
            }
        },

        applySseNotificationPreferences(preferences) {
            this.sseNotificationPreferences = normalizeSseNotificationPreferences(preferences);
        },

        async loadSseNotificationHistory() {
            try {
                const history = await loadNotificationHistory();
                const notifications = Array.isArray(history?.notifications) ? history.notifications : [];
                this.sseNotificationHistory = notifications;
            } catch (e) {
                console.warn('Failed to load notification history', e);
            }
        },

        async loadTransferItems() {
            try {
                const payload = await loadTransfers(this.ensureTabId());
                this.transferItems = Array.isArray(payload?.items) ? payload.items : [];
            } catch (e) {
                console.warn('Failed to load transfers', e);
            }
        },

        upsertTransferItem(transfer) {
            if (!transfer || typeof transfer !== 'object' || !transfer.transfer_id) return;

            const existing = Array.isArray(this.transferItems)
                ? this.transferItems.filter(item => item?.transfer_id !== transfer.transfer_id)
                : [];
            this.transferItems = [transfer, ...existing];
        },

        upsertSseNotificationHistory(notification) {
            if (!notification || typeof notification !== 'object' || !notification.id) return;

            const existing = Array.isArray(this.sseNotificationHistory)
                ? this.sseNotificationHistory.filter(item => item?.id !== notification.id)
                : [];

            this.sseNotificationHistory = [notification, ...existing];
        },

        removeSseNotificationHistory(notificationId) {
            const normalizedId = String(notificationId || '').trim();
            if (!normalizedId) return;

            this.sseNotificationHistory = (this.sseNotificationHistory || []).filter(
                item => String(item?.id || '') !== normalizedId,
            );
        },

        clearSseNotificationHistory() {
            this.sseNotificationHistory = [];
        },

        applySseNotificationCenterUpdate(payload = {}) {
            const action = String(payload.action || '').trim().toLowerCase();

            if (action === 'added') {
                this.upsertSseNotificationHistory(payload.notification);
                return;
            }

            if (action === 'deleted') {
                this.removeSseNotificationHistory(payload.id);
                return;
            }

            if (action === 'cleared') {
                this.clearSseNotificationHistory();
                return;
            }

            if (action === 'pruned') {
                const removedIds = new Set(
                    (Array.isArray(payload.ids) ? payload.ids : [])
                        .map(value => String(value || '').trim())
                        .filter(Boolean),
                );
                if (!removedIds.size) return;
                this.sseNotificationHistory = (this.sseNotificationHistory || []).filter(
                    item => !removedIds.has(String(item?.id || '').trim()),
                );
            }
        },

        buildSseNotificationMessage(message, actions = [], context = {}) {
            const normalizedActions = Array.isArray(actions) ? actions.filter(action => action?.label) : [];
            if (!normalizedActions.length) return message;

            const actionNodes = normalizedActions.map((action) => {
                const commonStyle = {
                    color: '#409eff',
                    cursor: 'pointer',
                    fontSize: '12px',
                    textDecoration: 'none',
                };

                if (action.url) {
                    return h('a', {
                        href: action.url,
                        target: '_blank',
                        rel: 'noopener noreferrer',
                        style: commonStyle,
                    }, action.label);
                }

                return h('button', {
                    type: 'button',
                    style: {
                        ...commonStyle,
                        padding: 0,
                        border: 'none',
                        background: 'transparent',
                    },
                    onClick: (event) => {
                        event?.preventDefault?.();
                        event?.stopPropagation?.();
                        void this.handleSseNotificationAction?.(action, context);
                    },
                }, action.label);
            });

            return h('div', null, [
                h('div', null, String(message || '')),
                h('div', {
                    style: {
                        display: 'flex',
                        flexWrap: 'wrap',
                        gap: '10px',
                        marginTop: '6px',
                    },
                }, actionNodes),
            ]);
        },

        showSseNotification(notificationKey, options = {}, recordContext = {}) {
            const preferences = this.sseNotificationPreferences || DEFAULT_SSE_NOTIFICATION_PREFERENCES;
            if (preferences.enabled === false) return;
            if (preferences.events?.[notificationKey] === false) return;

            const notificationOptions = { ...options };
            if (
                !notificationOptions.dangerouslyUseHTMLString
                && typeof notificationOptions.message === 'string'
                && Array.isArray(recordContext.actions)
                && recordContext.actions.length
            ) {
                notificationOptions.message = this.buildSseNotificationMessage(
                    notificationOptions.message,
                    recordContext.actions,
                    recordContext.context || {},
                );
            }

            ElNotification(notificationOptions);
        },

        // Toast lifetime is UI presentation policy; notification content and actions
        // come exclusively from the persisted server projection.
        getSseNotificationDuration(notification) {
            const key = notification.notification_key;
            const type = notification.type;
            if (key === 'connection_online' || key === 'connection_offline') return undefined;
            if (key === 'file_transfer_started') return 3500;
            if (key === 'file_transfer_stopped') return 4500;
            if (key === 'artifact_created' || (key === 'device_event' && type === 'info')) return 6000;
            if (key === 'pty_opened' || key === 'pty_closed'
                || key === 'screen_view_started' || key === 'screen_view_closed') return 4000;
            if (key === 'pty_error' || key === 'screen_view_error') return 5000;
            if (key === 'server_cleanup_completed' && type === 'warning') return 8000;
            return type === 'error' ? 7000 : 5000;
        },

        initSSE() {
            if (this.eventSource) this.eventSource.close();

            const tabId = this.ensureTabId();
            const es = openWebEventStream(tabId);
            this.eventSource = es;

            es.addEventListener('open', () => {
                const reconnecting = this.sseReady;
                this.sseReady = true;
                void this.$refs.executionInteractionDialogRef?.reloadPending(tabId);
                // Server replays bounded per-tab terminal events after a short
                // disconnect; the foreground snapshot still reconciles task state.
                void this.refreshForegroundTask?.();
            });

            es.addEventListener('foreground_task_changed', (event) => {
                const payload = JSON.parse(event.data || '{}');
                if (!payload.client_id || !payload.task) return;
                this.applyForegroundTaskUpdate?.(payload.client_id, payload.task);
            });

            es.addEventListener('interaction_requested', (event) => {
                const payload = JSON.parse(event.data || '{}');
                this.$refs.executionInteractionDialogRef?.enqueue(payload);
            });
            es.addEventListener('interaction_resolved', (event) => {
                const payload = JSON.parse(event.data || '{}');
                this.$refs.executionInteractionDialogRef?.resolved(payload);
            });

            es.addEventListener('notification_preferences_updated', (event) => {
                const payload = JSON.parse(event.data || '{}');
                this.applySseNotificationPreferences(payload);
            });

            es.addEventListener('notification_center_updated', (event) => {
                const payload = JSON.parse(event.data || '{}');
                this.applySseNotificationCenterUpdate(payload);
                if (payload.action !== 'added') return;
                const notification = payload.notification;
                if (!notification || !notification.notification_key) return;

                // The Notification Center is global; File Ready Toast remains
                // scoped to the currently selected device, as before.
                const clientId = notification.context?.client_id;
                if (notification.notification_key === 'artifact_created'
                    && this.selectedId && clientId && clientId !== this.selectedId) return;

                this.showSseNotification(notification.notification_key, {
                    title: notification.title,
                    message: notification.message,
                    type: notification.type,
                    duration: this.getSseNotificationDuration(notification),
                }, {
                    eventId: notification.event_id || event.lastEventId,
                    context: notification.context || {},
                    actions: notification.actions || [],
                });
            });

            es.addEventListener('external_tool_lifecycle', async () => {
                await this.refreshExternalToolsIfOpen?.();
            });

            es.addEventListener('agent_build_lifecycle', async (event) => {
                const payload = JSON.parse(event.data || '{}');
                if (String(payload.state || '').trim().toLowerCase() === 'completed') {
                    await this.refreshAgentOutputsIfOpen?.();
                }
            });

            es.addEventListener('device_monitor_snapshot', (event) => {
                const payload = JSON.parse(event.data || '{}');
                this.$refs.connectionInfoDialogRef?.handleDeviceMonitorSnapshot?.(payload);
                this.$refs.processDialogRef?.handleDeviceMonitorSnapshot?.(payload);
                this.$refs.logViewerDialogRef?.handleDeviceMonitorSnapshot?.(payload);
            });

            es.addEventListener('device_monitor_status', (event) => {
                const payload = JSON.parse(event.data || '{}');
                this.$refs.connectionInfoDialogRef?.handleDeviceMonitorStatus?.(payload);
                this.$refs.processDialogRef?.handleDeviceMonitorStatus?.(payload);
                this.$refs.logViewerDialogRef?.handleDeviceMonitorStatus?.(payload);
            });

            es.addEventListener('transfer_updated', (event) => {
                const payload = JSON.parse(event.data || '{}');
                this.upsertTransferItem(payload);
            });

            es.addEventListener('connection_online', (event) => {
                const payload = JSON.parse(event.data);
                const conn = payload.connection;
                this.upsertConnection(conn);
                if (conn.client_id === this.selectedId) void this.refreshForegroundTask?.();
            });

            es.addEventListener('connection_offline', (event) => {
                const payload = JSON.parse(event.data);
                const clientId = payload.client_id;
                const conn = payload.connection || this.connections.find(item => item.client_id === clientId) || {client_id: clientId};

                this.upsertConnection({
                    ...conn,
                    connection_state: 'offline',
                    disconnected_at: conn.disconnected_at || payload.time,
                    is_transfer_active: false,
                });

                this.clearActiveTask(clientId);
                this.applyForegroundTaskUpdate?.(clientId, { state: 'Idle' });
            });

            es.addEventListener('connection_heartbeat', (event) => {
                const payload = JSON.parse(event.data);
                const conn = payload.connection;
                //
                // //add
                // this.statusNowTick = Date.now();

                this.upsertConnection(conn);
            });

            const handleCommandResults = (payload, results) => {
                const items = Array.isArray(results) ? results : [];
                if (!items.length) return;
                this.noteTaskOutput?.(payload.task_id, items.length);
                const metadata = payload.metadata && typeof payload.metadata === 'object' ? payload.metadata : {};
                const isQuickActionDialog = metadata.quick_action === true && metadata.quick_action_presentation === 'dialog';
                const isScriptDialog = metadata.script_run === true && metadata.script_run_presentation === 'dialog';
                const terminalItems = [];
                let operationId = '';
                for (const item of items) {
                    const result = { ...payload, status: item.status, text: item.text, metadata };
                    const handledByQuickActionDialog = isQuickActionDialog
                        ? this.handleQuickActionCommandResult?.(result) === true : false;
                    const handledByTerminalCapture = this.routeTerminalTaskCapture?.('result', result) === true;
                    const handledByScriptDialog = isScriptDialog
                        ? this.handleScriptCommandResult?.(result) === true : false;
                    if (handledByQuickActionDialog || handledByScriptDialog || handledByTerminalCapture) continue;
                    if (!operationId) operationId = this.ensureTerminalTaskStart(result);
                    terminalItems.push({ text: item.text || '', meta: {
                        task_id: payload.task_id || '',
                        operation_id: operationId || '',
                        event_type: 'output',
                        command: payload.command || '',
                        command_id: payload.command_id ?? null,
                        metadata,
                    } });
                }
                if (terminalItems.length) this.appendOutputBatch(payload.client_id, terminalItems);
            };

            es.addEventListener('command_result', (event) => {
                const payload = JSON.parse(event.data);
                handleCommandResults(payload, [{ status: payload.status, text: payload.text }]);
            });

            es.addEventListener('command_result_batch', (event) => {
                const payload = JSON.parse(event.data);
                handleCommandResults(payload, payload.results);
            });

            es.addEventListener('command_complete', async (event) => {
                const payload = JSON.parse(event.data);
                const metadata = payload.metadata && typeof payload.metadata === 'object' ? {...payload.metadata} : {};
                const statusText = String(payload.status || '').trim();

                let finishText = 'Failed';
                let finishKind = 'error';

                if (statusText === 'cancelled' || payload.cancelled) {
                    finishText = 'Cancelled';
                    finishKind = 'info';
                } else if (payload.success) {
                    finishText = 'Success';
                    finishKind = 'success';
                }

                const isQuickActionDialog = metadata.quick_action === true && metadata.quick_action_presentation === 'dialog';
                const handledByQuickActionDialog = isQuickActionDialog
                    ? this.handleQuickActionCommandComplete?.({...payload, metadata}) === true
                    : false;


                const handledByTerminalCapture = this.routeTerminalTaskCapture?.('complete', payload) === true;
                const isScriptDialog = metadata.script_run === true && metadata.script_run_presentation === 'dialog';
                const handledByScriptDialog = isScriptDialog
                    ? this.handleScriptCommandComplete?.({...payload, metadata}) === true
                    : false;

                if (!handledByQuickActionDialog && !handledByScriptDialog && !handledByTerminalCapture) {
                    const operationId = this.ensureTerminalTaskStart(payload);
                    const finishedCommand = metadata.quick_action === true
                        ? (metadata.quick_action_display_command || payload.command)
                        : payload.command;
                    this.appendOutput(
                        payload.client_id,
                        formatTerminalCommandFinishedLine(finishedCommand, finishText),
                        finishKind,
                        {
                            task_id: payload.task_id || '',
                            operation_id: operationId || '',
                            event_type: 'completed',
                            execution_status: statusText,
                            execution_success: Boolean(payload.success),
                            command: payload.command || '',
                            command_id: payload.command_id ?? payload.source_command_id ?? null,
                            metadata,
                        }
                    );
                }

                // this.clearActiveTask(payload.client_id, payload.task_id);
                this.markTaskCompleted(payload.client_id, payload.task_id);

                const pendingRefresh = this.pendingRemoteUploadRefresh;
                if (
                    pendingRefresh &&
                    pendingRefresh.taskId &&
                    payload.task_id === pendingRefresh.taskId
                ) {
                    const refreshClientId = pendingRefresh.clientId;
                    const refreshPath = pendingRefresh.path || '';

                    this.pendingRemoteUploadRefresh = null;

                    if (payload.success && this.selectedId === refreshClientId) {
                        try {
                            if (pendingRefresh.source === 'script_remote_file_picker') {
                                await this.$refs.scriptLibraryDialogRef?.refreshRemoteFilePickerDirectory(refreshPath);
                            } else if (pendingRefresh.source === 'job_remote_file_picker') {
                                await this.$refs.backgroundJobsDialogRef?.refreshRemoteFilePickerDirectory(refreshPath);
                            } else if (pendingRefresh.source === 'external_tool_remote_file_picker') {
                                await this.$refs.externalToolManagerDialogRef?.loadRemoteFilePickerDirectory(refreshPath);
                            } else if (pendingRefresh.source === 'remote_file_picker') {
                                await this.$refs.scriptLibraryDialogRef?.refreshRemoteFilePickerDirectory(refreshPath);
                            } else if (this.remoteFilesDialogVisible) {
                                await this.loadRemoteDirectory(refreshPath);
                            }
                        } catch (e) {
                        }
                    }
                }

                this.reloadCommandCandidatesFromRuntime?.({
                    reset: true,
                    silent: true,
                });
                await this.loadConnections();
            });

            es.addEventListener('background_message', async (event) => {
                const payload = JSON.parse(event.data);
this.appendOutput(payload.client_id, `${TERMINAL_BACKGROUND_PREFIX} ${payload.text || ''}`, 'info');                await this.loadConnections();
            });

            es.addEventListener('background_job_status', async (event) => {
                const payload = JSON.parse(event.data);
                // this.scheduleBackgroundJobsRefresh(payload.client_id);
                this.scheduleBackgroundJobsRefresh?.(payload.client_id);
            });

            es.addEventListener('background_job_lifecycle', (event) => {
                const payload = JSON.parse(event.data || '{}');
                this.scheduleBackgroundJobsRefresh?.(payload.client_id);
            });

            es.addEventListener('background_job_message', async (event) => {
                const payload = JSON.parse(event.data);
                this.scheduleBackgroundJobsRefresh?.(payload.client_id);
                // this.scheduleBackgroundJobsRefresh(payload.client_id);
            });

            es.addEventListener('background_job_file', async (event) => {
                const payload = JSON.parse(event.data);
                // this.scheduleBackgroundJobsRefresh(payload.client_id);
                this.scheduleBackgroundJobsRefresh?.(payload.client_id);

                await this.refreshArtifactsIfOpen?.();
            });

            es.addEventListener('artifact_created', async (event) => {
                const payload = JSON.parse(event.data || '{}');
                if (!payload.artifact_id) return;

    //                 // Command Output 是用户主动保存的命令输出，不按“远程文件已准备好”处理。
    // if (payload.artifact_type === 'command_output') {
    //     await this.refreshArtifactsIfOpen?.();
    //     return;
    // }

                this.recordTerminalArtifact(payload);
                await this.refreshArtifactsIfOpen?.();
            });

            es.onerror = () => {
                // WebSocket transport reconnects and the next open resyncs authoritative task state
            };
        },

        ensureTabId() {
            const key = 'rat_web_tab_id';
            let tabId = '';

            try {
                tabId = String(sessionStorage.getItem(key) || '').trim();
            } catch (e) {
                tabId = '';
            }

            if (!tabId) {
                if (window.crypto && typeof window.crypto.randomUUID === 'function') {
                    tabId = window.crypto.randomUUID();
                } else {
                    tabId = `tab_${Date.now()}_${Math.random().toString(16).slice(2)}`;
                }

                try {
                    sessionStorage.setItem(key, tabId);
                } catch (e) {
                }
            }

            this.tabId = tabId;
            return tabId;
        },

        getTabScopedHeaders(extra = {}) {
            const headers = {...extra};
            if (this.tabId) {
                headers['X-Tab-Id'] = this.tabId;
            }
            return headers;
        },
    }
};