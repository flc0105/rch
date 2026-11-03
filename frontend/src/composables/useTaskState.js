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
        setActiveTask(clientId, taskId, cancelPolicy = '', historyEntryId = '') {
            if (!clientId) return;

            const normalizedTaskId = String(taskId || '').trim();

            if (!normalizedTaskId) {
                this.clearActiveTask(clientId);
                return;
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

        noteTaskOutput(taskId) {
            const id = String(taskId || '').trim();
            if (id) this.taskOutputCounts = { ...this.taskOutputCounts, [id]: (this.taskOutputCounts[id] || 0) + 1 };
        },

        async recoverFinishedTask(clientId, taskId, historyEntryId = '') {
            const id = String(taskId || '').trim();
            if (!id || this.completedTaskIds[id]) return;
            const entryId = String(historyEntryId || this.activeTaskHistoryIds[id] || '').trim();
            const conn = (this.connections || []).find(item => item.client_id === clientId);
            const machineId = String(conn?.machine_id || '').trim();
            const alreadyDelivered = this.taskOutputCounts[id] || 0;
            // Release the UI immediately, even when the history endpoint is temporarily unavailable.
            this.markTaskCompleted(clientId, id);
            if (!entryId || !machineId) return;
            try {
                const { getCommandExecutionEntry } = await import('../api/commandHistoryApi.js');
                const entry = await getCommandExecutionEntry(machineId, entryId);
                if (entry.client_id !== clientId || !entry.finished_at) return;
                // Dialog presentations own their output; do not echo them into Terminal.
                if (entry.presentation && entry.presentation !== 'terminal') return;
                const records = entry.result?.output_records || [];
                for (const record of records.slice(alreadyDelivered)) {
                    this.appendOutput(clientId, record.text || '', '', {
                        task_id: id, history_entry_id: entryId, recovered: true,
                    });
                }
                const { formatTerminalCommandFinishedLine } = await import('./terminalMarkers.js');
                this.appendOutput(clientId, formatTerminalCommandFinishedLine(
                    entry.invocation?.input || entry.action || '',
                    entry.status === 'success' ? 'Success' : 'Failed',
                ), entry.status === 'success' ? 'success' : 'error', { task_id: id, recovered: true });
            } catch (error) {
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