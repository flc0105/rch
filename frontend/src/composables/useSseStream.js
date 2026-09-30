import { h } from 'vue';
import {
    formatTerminalCommandFinishedLine,
    TERMINAL_BACKGROUND_PREFIX,
    TERMINAL_FILE_READY_PREFIX,
} from './terminalMarkers.js';
import { openSseStream } from '../api/streamApi.js';
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

            ElementPlus.ElNotification(notificationOptions);
        },

        initSSE() {
            if (this.eventSource) this.eventSource.close();

            const tabId = this.ensureTabId();
            const es = openSseStream(tabId);
            this.eventSource = es;

            const getConnectionLabel = (clientId) => {
                const normalizedClientId = String(clientId || '').trim();
                const conn = this.connections.find(item => item.client_id === normalizedClientId) || {};
                return conn.hostname || conn.client_id || normalizedClientId || 'Unknown device';
            };

            es.addEventListener('open', () => {
                if (!this.sseReady) this.sseReady = true;
            });

            es.addEventListener('notification_preferences_updated', (event) => {
                const payload = JSON.parse(event.data || '{}');
                this.applySseNotificationPreferences(payload);
            });

            es.addEventListener('notification_center_updated', (event) => {
                const payload = JSON.parse(event.data || '{}');
                this.applySseNotificationCenterUpdate(payload);
            });

            es.addEventListener('server_cleanup_completed', (event) => {
                const payload = JSON.parse(event.data || '{}');
                const removedFiles = Number(payload.removed_files || 0);
                const removedRecords = Number(payload.removed_records || 0);
                const bytesFreed = Number(payload.bytes_freed || 0);
                const errorCount = Number(payload.error_count || 0);
                const logUrl = String(payload.log_url || '').trim();
                const sizeLabel = typeof this.formatBytes === 'function'
                    ? this.formatBytes(bytesFreed)
                    : `${bytesFreed} B`;
                const messageParts = [
                    `${removedFiles} file${removedFiles === 1 ? '' : 's'}`,
                    `${removedRecords} record${removedRecords === 1 ? '' : 's'}`,
                    sizeLabel,
                ];
                if (errorCount) messageParts.push(`${errorCount} error${errorCount === 1 ? '' : 's'}`);

                this.showSseNotification('server_cleanup_completed', {
                    title: errorCount ? 'Server Cleanup Completed with Errors' : 'Server Cleanup Completed',
                    message: messageParts.join(' · '),
                    type: errorCount ? 'warning' : 'success',
                    duration: errorCount ? 8000 : 5000,
                }, {
                    eventId: event.lastEventId,
                    context: {
                        run_id: payload.run_id || '',
                        trigger: payload.trigger || '',
                        removed_files: removedFiles,
                        removed_dirs: Number(payload.removed_dirs || 0),
                        removed_records: removedRecords,
                        bytes_freed: bytesFreed,
                        error_count: errorCount,
                    },
                    actions: logUrl ? [{
                        id: 'view-cleanup-log',
                        type: 'view_server_cleanup_log',
                        label: 'View Cleanup Log',
                        url: logUrl,
                    }] : [],
                });
            });

            es.addEventListener('external_tool_lifecycle', async (event) => {
                const payload = JSON.parse(event.data || '{}');
                const action = String(payload.action || '').trim().toLowerCase();
                const state = String(payload.state || '').trim().toLowerCase();
                const operation = String(payload.operation || '').trim().toLowerCase();
                const deviceName = getConnectionLabel(payload.client_id);
                const serviceName = payload.display_name || payload.tool_id || payload.package_id || 'external tool';
                const instanceId = String(payload.instance_id || '').trim();
                const instanceLabel = instanceId ? `/${instanceId}` : '';
                const serviceLabel = `${serviceName}${instanceLabel}`;
                const errorText = String(payload.error || payload.message || '').trim();
                const notificationKey = {
                    'daemon:started': 'external_tool_daemon_started',
                    'daemon:stopped': 'external_tool_daemon_stopped',
                    'daemon:error': 'external_tool_daemon_error',
                    'install:completed': 'external_tool_install_completed',
                    'install:failed': 'external_tool_install_failed',
                    'uninstall:completed': 'external_tool_uninstall_completed',
                    'uninstall:failed': 'external_tool_uninstall_failed',
                }[`${action}:${state}`];

                if (!notificationKey) {
                    await this.refreshExternalToolsIfOpen?.();
                    return;
                }

                const context = {
                    client_id: payload.client_id || '',
                    action,
                    state,
                    operation,
                    tool_id: payload.tool_id || '',
                    package_id: payload.package_id || '',
                    module_id: payload.module_id || '',
                    display_name: payload.display_name || '',
                    instance_id: instanceId,
                    status: payload.status || '',
                    pid: payload.pid ?? null,
                    returncode: payload.returncode ?? null,
                    duration_sec: payload.duration_sec ?? null,
                    error: payload.error || '',
                    log_excerpt: payload.log_excerpt || '',
                };
                const actions = [
                    {
                        id: 'open-external-tools',
                        type: 'open_external_tools',
                        label: 'Open External Tools',
                    },
                ];
                if (state === 'error' || state === 'failed') {
                    actions.push({
                        id: 'view-log',
                        type: 'view_external_tool_log',
                        label: 'View Log',
                    });
                }

                let title = 'External Tool';
                let type = 'info';
                let message = `${deviceName} · ${serviceLabel} updated`;

                if (action === 'daemon' && state === 'started') {
                    title = 'External Tool Daemon Started';
                    type = 'success';
                    message = `${deviceName} · ${serviceLabel} daemon started successfully`;
                } else if (action === 'daemon' && state === 'stopped') {
                    title = 'External Tool Daemon Stopped';
                    type = 'warning';
                    message = `${deviceName} · ${serviceLabel} daemon stopped successfully`;
                } else if (action === 'daemon' && state === 'error') {
                    title = operation === 'stop' ? 'External Tool Daemon Stop Error' : 'External Tool Daemon Start Error';
                    type = 'error';
                    message = `${deviceName} · ${serviceLabel} daemon ${operation || 'operation'} failed${errorText ? `: ${errorText}` : ''}`;
                } else if (action === 'install' && state === 'completed') {
                    title = 'External Tool Install Completed';
                    type = 'success';
                    message = `${deviceName} · ${serviceName} install completed${payload.message ? `: ${payload.message}` : ' successfully'}`;
                } else if (action === 'install' && state === 'failed') {
                    title = 'External Tool Install Failed';
                    type = 'error';
                    message = `${deviceName} · ${serviceName} install failed${errorText ? `: ${errorText}` : ''}`;
                } else if (action === 'uninstall' && state === 'completed') {
                    title = 'External Tool Uninstall Completed';
                    type = 'success';
                    message = `${deviceName} · ${serviceName} uninstall completed${payload.message ? `: ${payload.message}` : ' successfully'}`;
                } else if (action === 'uninstall' && state === 'failed') {
                    title = 'External Tool Uninstall Failed';
                    type = 'error';
                    message = `${deviceName} · ${serviceName} uninstall failed${errorText ? `: ${errorText}` : ''}`;
                }

                this.showSseNotification(notificationKey, {
                    title,
                    message,
                    type,
                    duration: type === 'error' ? 7000 : 5000,
                }, {
                    eventId: event.lastEventId,
                    context,
                    actions,
                });

                await this.refreshExternalToolsIfOpen?.();
            });

            es.addEventListener('agent_build_lifecycle', async (event) => {
                const payload = JSON.parse(event.data || '{}');
                const state = String(payload.state || '').trim().toLowerCase();
                const notificationKey = {
                    completed: 'agent_build_completed',
                    error: 'agent_build_error',
                }[state];
                if (!notificationKey) return;

                const targetOs = String(payload.target_os || '').trim();
                const targetArch = String(payload.target_arch || '').trim();
                const builder = String(payload.builder || '').trim();
                const fileName = String(payload.file_name || '').trim();
                const errorText = String(payload.error || '').trim();
                const context = {
                    state,
                    builder,
                    target_os: targetOs,
                    target_arch: targetArch,
                    source: payload.source || '',
                    file_name: fileName,
                    error: errorText,
                };
                const actions = [];

                if (state === 'completed' && payload.download_url) {
                    actions.push({
                        id: 'download',
                        type: 'agent_download',
                        label: 'Download',
                        url: payload.download_url,
                    });
                }
                actions.push({
                    id: 'open-agents',
                    type: 'open_agents',
                    label: 'Open Agents',
                });

                let title = 'Agent Build';
                let type = 'info';
                let message = '';
                if (state === 'completed') {
                    title = 'Agent Build Completed';
                    type = 'success';
                    message = `Agent build completed successfully${fileName ? ` · ${fileName}` : ''}`;
                } else if (state === 'error') {
                    title = 'Agent Build Error';
                    type = 'error';
                    message = `Agent build failed${errorText ? `: ${errorText}` : ''}`;
                }

                this.showSseNotification(notificationKey, {
                    title,
                    message,
                    type,
                    duration: state === 'error' ? 7000 : 5000,
                }, {
                    eventId: event.lastEventId,
                    context,
                    actions,
                });

                if (state === 'completed') {
                    await this.refreshAgentOutputsIfOpen?.();
                }
            });

            es.addEventListener('device_monitor_snapshot', (event) => {
                const payload = JSON.parse(event.data || '{}');
                this.$refs.connectionInfoDialogRef?.handleDeviceMonitorSnapshot?.(payload);
                this.$refs.processDialogRef?.handleDeviceMonitorSnapshot?.(payload);
            });

            es.addEventListener('device_monitor_status', (event) => {
                const payload = JSON.parse(event.data || '{}');
                this.$refs.connectionInfoDialogRef?.handleDeviceMonitorStatus?.(payload);
                this.$refs.processDialogRef?.handleDeviceMonitorStatus?.(payload);
            });

            es.addEventListener('transfer_updated', (event) => {
                const payload = JSON.parse(event.data || '{}');
                this.upsertTransferItem(payload);
            });

            es.addEventListener('file_transfer_lifecycle', (event) => {
                const payload = JSON.parse(event.data || '{}');
                const lifecycle = String(payload.lifecycle || '').trim().toLowerCase();
                const state = String(payload.state || '').trim().toLowerCase();
                const filename = String(payload.filename || 'File transfer').trim() || 'File transfer';
                const deviceName = getConnectionLabel(payload.client_id);
                const stage = String(payload.stage || '').trim().toLowerCase();
                const direction = String(payload.direction || '').trim().toLowerCase();
                const errorText = String(payload.error || '').trim();

                let routeLabel = '';
                if (stage === 'uploading_to_server') {
                    routeLabel = 'Browser → Server';
                } else if (direction === 'server_to_client') {
                    routeLabel = `Server → ${deviceName}`;
                } else {
                    routeLabel = `${deviceName} → Server`;
                }

                const actions = [
                    {
                        id: 'open-transfers',
                        type: 'open_transfers',
                        label: 'Open Transfers',
                    },
                ];
                const context = {
                    transfer_id: payload.transfer_id || '',
                    client_id: payload.client_id || '',
                    filename,
                    direction,
                    state,
                    stage,
                };

                if (lifecycle === 'started') {
                    this.showSseNotification('file_transfer_started', {
                        title: 'File Transfer Started',
                        message: `${filename} · ${routeLabel}`,
                        type: 'info',
                        duration: 3500,
                    }, {
                        eventId: event.lastEventId,
                        context,
                        actions,
                    });
                    return;
                }

                if (lifecycle === 'stopped') {
                    const cancelled = state === 'cancelled';
                    this.showSseNotification('file_transfer_stopped', {
                        title: cancelled ? 'File Transfer Stopped' : 'File Transfer Completed',
                        message: cancelled
                            ? `${filename} · Cancelled · ${routeLabel}`
                            : `${filename} · Completed · ${routeLabel}`,
                        type: cancelled ? 'warning' : 'success',
                        duration: 4500,
                    }, {
                        eventId: event.lastEventId,
                        context,
                        actions,
                    });
                    return;
                }

                if (lifecycle === 'error') {
                    this.showSseNotification('file_transfer_error', {
                        title: 'File Transfer Error',
                        message: `${filename} · ${routeLabel}${errorText ? `: ${errorText}` : ''}`,
                        type: 'error',
                        duration: 7000,
                    }, {
                        eventId: event.lastEventId,
                        context: { ...context, error: errorText },
                        actions,
                    });
                }
            });

            es.addEventListener('connection_online', (event) => {
                const payload = JSON.parse(event.data);
                const conn = payload.connection;
                this.upsertConnection(conn);

                this.showSseNotification('connection_online', {
                    title: 'Device Online',
                    message: `${conn.hostname || conn.client_id} is now available`,
                    type: 'success'
                }, {
                    eventId: event.lastEventId,
                    context: {
                        client_id: conn.client_id || '',
                        hostname: conn.hostname || '',
                    },
                });
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

                this.showSseNotification('connection_offline', {
                    title: 'Device Offline',
                    message: `${(conn && conn.hostname) || clientId} went offline`,
                    type: 'warning'
                }, {
                    eventId: event.lastEventId,
                    context: {
                        client_id: clientId || '',
                        hostname: conn?.hostname || '',
                    },
                });
            });

            es.addEventListener('connection_heartbeat', (event) => {
                const payload = JSON.parse(event.data);
                const conn = payload.connection;
                //
                // //add
                // this.statusNowTick = Date.now();

                this.upsertConnection(conn);
            });

            es.addEventListener('command_result', (event) => {
                const payload = JSON.parse(event.data);
                const metadata = payload.metadata && typeof payload.metadata === 'object' ? payload.metadata : {};
                const isQuickActionDialog = metadata.quick_action === true && metadata.quick_action_presentation === 'dialog';
                const handledByQuickActionDialog = isQuickActionDialog
                    ? this.handleQuickActionCommandResult?.({...payload, metadata}) === true
                    : false;

                if (!handledByQuickActionDialog) {
                    this.appendOutput(payload.client_id, payload.text || '', '', {
                        task_id: payload.task_id || '',
                        command: payload.command || '',
                        command_id: payload.command_id ?? null,
                        metadata,
                    });
                }
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

                if (!handledByQuickActionDialog) {
                    const finishedCommand = metadata.quick_action === true
                        ? (metadata.quick_action_display_command || payload.command)
                        : payload.command;
                    this.appendOutput(
                        payload.client_id,
                        formatTerminalCommandFinishedLine(finishedCommand, finishText),
                        finishKind,
                        {
                            task_id: payload.task_id || '',
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

            es.addEventListener('background_job_lifecycle', async (event) => {
                const payload = JSON.parse(event.data || '{}');
                const state = String(payload.state || payload.status || '').trim().toLowerCase();
                const jobName = payload.display_name || payload.job_key || payload.job_name || 'background job';
                const deviceName = getConnectionLabel(payload.client_id);

                let title = 'Background Job';
                let type = 'info';
                let stateText = state || 'updated';

                if (state === 'running') {
                    title = 'Background Job Started';
                    type = 'success';
                    stateText = 'started';
                } else if (state === 'stopped') {
                    title = 'Background Job Finished';
                    type = 'success';
                    stateText = 'finished';
                } else if (state === 'error') {
                    title = 'Background Job Error';
                    type = 'error';
                    stateText = 'ended with error';
                }

                const notificationKey = {
                    running: 'background_job_running',
                    stopped: 'background_job_stopped',
                    error: 'background_job_error',
                }[state] || `background_job_${state || 'updated'}`;

                this.showSseNotification(notificationKey, {
                    title,
                    message: `${jobName} ${stateText} on ${deviceName}`,
                    type,
                    duration: 5000,
                }, {
                    eventId: event.lastEventId,
                    context: {
                        client_id: payload.client_id || '',
                        job_id: payload.job_id || '',
                        job_key: payload.job_key || payload.job_name || '',
                        display_name: payload.display_name || '',
                        state,
                    },
                });

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

            es.addEventListener('pty_lifecycle', (event) => {
                const payload = JSON.parse(event.data || '{}');
                const state = String(payload.state || '').trim().toLowerCase();
                const deviceName = getConnectionLabel(payload.client_id);

                if (state === 'opened') {
                    this.showSseNotification('pty_opened', {
                        title: 'PTY Started',
                        message: `PTY session started on ${deviceName}`,
                        type: 'success',
                        duration: 4000,
                    }, {
                        eventId: event.lastEventId,
                        context: {
                            client_id: payload.client_id || '',
                            pty_session_id: payload.pty_session_id || '',
                            state,
                        },
                    });
                    return;
                }

                if (state === 'closed') {
                    const exitCode = payload.exit_code === null || payload.exit_code === undefined
                        ? ''
                        : `, exit=${payload.exit_code}`;
                    this.showSseNotification('pty_closed', {
                        title: 'PTY Stopped',
                        message: `PTY session stopped on ${deviceName}${exitCode}`,
                        type: 'warning',
                        duration: 4000,
                    }, {
                        eventId: event.lastEventId,
                        context: {
                            client_id: payload.client_id || '',
                            pty_session_id: payload.pty_session_id || '',
                            state,
                            exit_code: payload.exit_code ?? null,
                        },
                    });
                    return;
                }

                if (state === 'error') {
                    this.showSseNotification('pty_error', {
                        title: 'PTY Error',
                        message: payload.error
                            ? `PTY session ended on ${deviceName}: ${payload.error}`
                            : `PTY session ended with an error on ${deviceName}`,
                        type: 'error',
                        duration: 5000,
                    }, {
                        eventId: event.lastEventId,
                        context: {
                            client_id: payload.client_id || '',
                            pty_session_id: payload.pty_session_id || '',
                            state,
                            error: payload.error || '',
                        },
                    });
                }
            });

            es.addEventListener('screen_view_lifecycle', (event) => {
                const payload = JSON.parse(event.data || '{}');
                const state = String(payload.state || '').trim().toLowerCase();
                const deviceName = getConnectionLabel(payload.client_id);

                if (state === 'started') {
                    this.showSseNotification('screen_view_started', {
                        title: 'Screen View Started',
                        message: `Screen view started on ${deviceName}`,
                        type: 'success',
                        duration: 4000,
                    }, {
                        eventId: event.lastEventId,
                        context: {
                            client_id: payload.client_id || '',
                            screen_session_id: payload.screen_session_id || '',
                            state,
                        },
                    });
                    return;
                }

                if (state === 'closed') {
                    this.showSseNotification('screen_view_closed', {
                        title: 'Screen View Stopped',
                        message: `Screen view stopped on ${deviceName}`,
                        type: 'warning',
                        duration: 4000,
                    }, {
                        eventId: event.lastEventId,
                        context: {
                            client_id: payload.client_id || '',
                            screen_session_id: payload.screen_session_id || '',
                            state,
                        },
                    });
                    return;
                }

                if (state === 'error') {
                    this.showSseNotification('screen_view_error', {
                        title: 'Screen View Error',
                        message: payload.error
                            ? `Screen view ended on ${deviceName}: ${payload.error}`
                            : `Screen view ended with an error on ${deviceName}`,
                        type: 'error',
                        duration: 5000,
                    }, {
                        eventId: event.lastEventId,
                        context: {
                            client_id: payload.client_id || '',
                            screen_session_id: payload.screen_session_id || '',
                            state,
                            error: payload.error || '',
                        },
                    });
                }
            });

            es.addEventListener('artifact_created', async (event) => {
                const payload = JSON.parse(event.data || '{}');
                const fileName = payload.original_name || payload.stored_name || 'file';

                if (!payload.artifact_id) return;

    //                 // Command Output 是用户主动保存的命令输出，不按“远程文件已准备好”处理。
    // if (payload.artifact_type === 'command_output') {
    //     await this.refreshArtifactsIfOpen?.();
    //     return;
    // }

                if (payload.client_id) {
                    this.appendOutput(
    payload.client_id,
    `${TERMINAL_FILE_READY_PREFIX} ${fileName}`,
    'success',
    {
        artifactInfo: {
            artifact_id: payload.artifact_id || '',
            artifact_type: payload.artifact_type || '',
            category: payload.category || '',
            original_name: payload.original_name || fileName,
        },
    }
);
                }

                if (!this.selectedId || payload.client_id === this.selectedId || !payload.client_id) {
                    const downloadUrl = payload.download_url || `/api/artifacts/${encodeURIComponent(payload.artifact_id)}/download`;
                    const context = {
                        client_id: payload.client_id || '',
                        artifact_id: payload.artifact_id || '',
                        artifact_type: payload.artifact_type || '',
                        category: payload.category || '',
                        original_name: payload.original_name || fileName,
                    };
                    const actions = [
                        { id: 'download', type: 'artifact_download', label: 'Download', url: downloadUrl },
                        { id: 'preview', type: 'artifact_preview', label: 'Preview' },
                        { id: 'open-artifacts', type: 'open_artifacts', label: 'Open Artifacts' },
                    ];
                    this.showSseNotification('artifact_created', {
                        title: 'File Ready',
                        message: `${fileName} has been saved`,
                        type: 'success',
                        duration: 6000
                    }, {
                        eventId: event.lastEventId,
                        context,
                        actions,
                    });
                }

                await this.refreshArtifactsIfOpen?.();
            });


            es.onerror = () => {
                // EventSource reconnects automatically
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