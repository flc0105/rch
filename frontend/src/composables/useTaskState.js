import { activityOutputRecords } from '../utils/activityOutput.js'

export default {
    data() {
        return {
            activeTaskIds: {},
            activeTaskHistoryIds: {},
            taskOutputCounts: {},
            activeTaskCancelPolicies: {},
            completedTaskIds: {},
        }
    },

    methods: {
        setActiveTask(clientId, taskId, cancelPolicy = '', historyEntryId = '', operationId = '') {
            if (!clientId) return;

            const normalizedTaskId = String(taskId || '').trim();

            if (!normalizedTaskId) {
                this.clearActiveTask(clientId);
                return;
            }

            const operation = this.terminalOperationRegistry?.[String(operationId || '')];
            if (operation && String(operation.client_id) === String(clientId)) {
                operation.task_id = normalizedTaskId;
                if (operation.status === 'submitting') operation.status = 'accepted';
            }

            // 处理极短命令 race：complete SSE 可能早于 POST 返回。
            // 如果 task 已经完成过，不允许它再被迟到的 setActiveTask 写回 Busy。
            if (this.completedTaskIds[normalizedTaskId]) {
                this.clearActiveTask(clientId, normalizedTaskId);
                return;
            }

            this.activeTaskIds = {
                ...this.activeTaskIds,
                [clientId]: normalizedTaskId
            };
            if (historyEntryId) this.activeTaskHistoryIds = { ...this.activeTaskHistoryIds, [normalizedTaskId]: historyEntryId };
            this.activeTaskCancelPolicies = {
                ...this.activeTaskCancelPolicies,
                [clientId]: cancelPolicy === 'none' ? 'none' : '',
            };
        },

        markTaskCompleted(clientId, taskId = '') {
            const normalizedTaskId = String(taskId || '').trim();

            if (normalizedTaskId) {
                const nextCompletedTaskIds = {
                    ...this.completedTaskIds,
                    [normalizedTaskId]: Date.now(),
                };

                // 只保留少量 tombstone，避免长期运行时无限增长。
                const entries = Object.entries(nextCompletedTaskIds)
                    .sort((a, b) => Number(a[1] || 0) - Number(b[1] || 0));

                while (entries.length > 300) {
                    const [oldestTaskId] = entries.shift();
                    delete nextCompletedTaskIds[oldestTaskId];
                }

                this.completedTaskIds = nextCompletedTaskIds;
            }

            this.clearActiveTask(clientId, normalizedTaskId);
            if (normalizedTaskId) {
                const histories = {...this.activeTaskHistoryIds};
                delete histories[normalizedTaskId];
                this.activeTaskHistoryIds = histories;
                const counts = {...this.taskOutputCounts};
                delete counts[normalizedTaskId];
                this.taskOutputCounts = counts;
            }
        },

        noteTaskOutput(taskId, count = 1) {
            const id = String(taskId || '').trim();
            if (id) this.taskOutputCounts = { ...this.taskOutputCounts, [id]: (this.taskOutputCounts[id] || 0) + count };
        },

        async recoverFinishedTask(clientId, taskId, historyEntryId = '', foregroundEnded = false) {
            const id = String(taskId || '').trim();
            if (!id || this.completedTaskIds[id]) return;
            const entryId = String(historyEntryId || this.activeTaskHistoryIds[id] || '').trim();
            const conn = (this.connections || []).find(item => item.client_id === clientId);
            const machineId = String(conn?.machine_id || '').trim();
            // An Idle foreground slot says nothing about an independent task.
            // Only a known slot release or a finished Activity can retire it.
            if (!entryId || !machineId) {
                if (foregroundEnded) this.markTaskCompleted(clientId, id);
                return;
            }
            try {
                const { getCommandExecutionEntry } = await import('../api/commandHistoryApi.js');
                const entry = await getCommandExecutionEntry(machineId, entryId);
                if (this.completedTaskIds[id]) return;
                if (entry.client_id !== clientId || !entry.finished_at) {
                    if (foregroundEnded) this.markTaskCompleted(clientId, id);
                    return;
                }
                // A live event may have arrived while the Activity was loading.
                const alreadyDelivered = this.taskOutputCounts[id] || 0;
                this.markTaskCompleted(clientId, id);
                // Dialog presentations own their output; do not echo them into Terminal.
                if (entry.presentation && entry.presentation !== 'terminal') return;
                const records = activityOutputRecords(entry.result, { terminal: true, outputTexts: entry.output_texts });
                for (const record of records.slice(alreadyDelivered)) {
                    this.appendOutput(clientId, record.text || '', '', {
                        task_id: id, history_entry_id: entryId, recovered: true,
                    });
                }
                if (entry.result_omitted) {
                    this.appendOutput(clientId, '[Some history output was not saved]', 'warning', {
                        task_id: id, history_entry_id: entryId, recovered: true,
                    });
                }
                const { formatTerminalCommandFinishedLine } = await import('./terminalMarkers.js');
                // Recovery must use the persisted terminal status, just like
                // the live command_complete event; false success != error.
                const terminalStates = {
                    success: ['Success', 'success'],
                    partial: ['Partial', 'warning'],
                    error: ['Failed', 'error'],
                    cancelled: ['Cancelled', 'info'],
                    timed_out: ['Timed out', 'error'],
                    interrupted: ['Interrupted', 'error'],
                };
                const [finishText, finishKind] = terminalStates[entry.status] || terminalStates.error;
                this.appendOutput(clientId, formatTerminalCommandFinishedLine(
                    entry.invocation?.command || entry.action || '', finishText,
                ), finishKind, { task_id: id, recovered: true, execution_status: entry.status });
            } catch (error) {
                if (foregroundEnded && !this.completedTaskIds[id]) this.markTaskCompleted(clientId, id);
                console.warn('Unable to recover finished task output', error);
            }
        },

        clearActiveTask(clientId, taskId = '') {
            if (!clientId) return;

            const currentTaskId = this.activeTaskIds[clientId] || '';
            if (taskId && currentTaskId && currentTaskId !== taskId) {
                return;
            }

            const nextActive = {...this.activeTaskIds};
            delete nextActive[clientId];
            this.activeTaskIds = nextActive;
            const nextPolicies = { ...this.activeTaskCancelPolicies };
            delete nextPolicies[clientId];
            this.activeTaskCancelPolicies = nextPolicies;
        },
    },

    computed: {
        currentActiveTaskId() {
            return this.activeTaskIds[this.selectedId] || '';
        },
        currentActiveTaskCancelPolicy() {
            return this.activeTaskCancelPolicies[this.selectedId] || '';
        },
    },
}