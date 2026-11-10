import { TERMINAL_HISTORY } from '../data/terminalHistoryConfig.js'
import { TerminalHistoryStore, trimTerminalWindow, splitLongTerminalLine } from '../utils/terminalHistoryStore.js'
import { ElMessage } from 'element-plus'
import { isJsonContainerText, isJsonStartLine, parseJsonLines, jsonBracketDelta } from '../utils/terminalJson.js'
import { createTerminalOperation } from '../utils/terminalOperation.js'
import {
    TERMINAL_BACKGROUND_PREFIX,
    isTerminalCancelRequestedText,
    isTerminalCommandFailedText,
    isTerminalCommandFinishedText,
} from './terminalMarkers.js';

export default {
    data() {
        return {
            outputs: {},
            terminalOperationRegistry: {},
            terminalArtifactLinks: {},
            terminalViewStates: {},
            terminalNotices: {},
        }
    },

    methods: {


        isTerminalJsonText(text) { return isJsonContainerText(text) },
        isTerminalJsonStartLine(text) { return isJsonStartLine(text) },
        tryParseTerminalJsonBuffer(lines) { return parseJsonLines(lines) },

//    inferLineKind(text) {
//     const value = String(text ?? '');
//     if (value.startsWith('> ')) return 'command';
//     if (value.startsWith(TERMINAL_BACKGROUND_PREFIX) || isTerminalCancelRequestedText(value)) return 'info';
//     if (isTerminalCommandFinishedText(value)) {
//         if (/Success/i.test(value)) return 'success';
//         if (/Cancelled/i.test(value)) return 'info';
//         return 'error';
//     }
//     if (isTerminalCommandFailedText(value)) return 'error';
//     if (/failed|error|not found|denied|unable/i.test(value)) return 'error';
//     if (/completed|success|saved|started|uploaded|downloaded|created|renamed|copied/i.test(value)) return 'success';
//     if (/preparing|loading|refresh|connected|disconnected|warning/i.test(value)) return 'info';
//     return 'default';
// },
//


        inferLineKind(text) {
    const value = String(text ?? '');
    const trimmedValue = value.trimStart();

    // 用户自定义终端前缀：
    // [+] 成功
    // [-] 错误
    // [!] 警告
    // [*] 普通信息
    if (/^\[\+\](?:\s|$)/.test(trimmedValue)) return 'success';
    if (/^\[-\](?:\s|$)/.test(trimmedValue)) return 'error';
    if (/^\[!\](?:\s|$)/.test(trimmedValue)) return 'warning';
    if (/^\[\*\](?:\s|$)/.test(trimmedValue)) return 'info';

    if (value.startsWith('> ')) return 'command';

    if (
        value.startsWith(TERMINAL_BACKGROUND_PREFIX) ||
        isTerminalCancelRequestedText(value)
    ) {
        return 'info';
    }

    if (isTerminalCommandFinishedText(value)) {
        if (/Success/i.test(value)) return 'success';
        if (/Cancelled/i.test(value)) return 'info';
        return 'error';
    }

    if (isTerminalCommandFailedText(value)) return 'error';

    if (/failed|error|not found|denied|unable/i.test(value)) {
        return 'error';
    }

    if (/completed|success|saved|started|uploaded|downloaded|created|renamed|copied/i.test(value)) {
        return 'success';
    }

    if (/preparing|loading|refresh|connected|disconnected|warning/i.test(value)) {
        return 'info';
    }

    return 'default';
},

        calculateTerminalJsonDelta(text) { return jsonBracketDelta(text) },

  isTerminalCommandBoundaryLine(text) {
    const raw = String(text ?? '');
    return raw.startsWith('> ') || isTerminalCommandFinishedText(raw) || isTerminalCommandFailedText(raw);
},

        buildTerminalOutputLine(segment, kind = '', meta = {}) {
            const lineText = segment === '' ? ' ' : segment;
            const line = {
                text: lineText,
                kind: kind || (meta?.event_type === 'output' && String(segment).startsWith('> ')
                    ? 'default' : this.inferLineKind(segment)),
                isMultiline: false,
                isArtifactMessage: false,
                artifactInfo: null,
                isJsonMessage: false,
                jsonText: '',
                meta: meta && typeof meta === 'object' ? { ...meta } : {}
            };

            if (meta && typeof meta === 'object') {
                if (meta.artifactInfo && meta.artifactInfo.artifact_id) {
                    line.isArtifactMessage = true;
                    line.artifactInfo = {...meta.artifactInfo};
                }

                if (meta.forceJson === true) {
                    line.isJsonMessage = true;
                    line.jsonText = String(meta.jsonText || '');
                }
            }

            return line;
        },

        getTerminalCommandGroupStartIndex(lines, endIndex) {
            const safeLines = Array.isArray(lines) ? lines : [];
            for (let i = endIndex; i >= 0; i--) {
                const line = safeLines[i];
                if (!line) continue;

                if (line.kind === 'command') {
                    return i;
                }

                if (i < endIndex && this.isCommandFinishedLine(line)) {
                    return i + 1;
                }
            }
            return 0;
        },

        recordTerminalArtifact(payload) {
            const clientId = String(payload?.client_id || '').trim();
            const sourceCommandId = String(payload?.source_command_id ?? '').trim();
            const artifactId = String(payload?.artifact_id || '').trim();
            if (!clientId || !sourceCommandId || !artifactId) return;

            const existing = this.terminalArtifactLinks[clientId] || [];
            if (existing.some(item => item.artifact_id === artifactId)) return;
            this.terminalArtifactLinks[clientId] = [...existing, {
                artifact_id: artifactId,
                source_command_id: sourceCommandId,
                artifact_type: String(payload.artifact_type || ''),
                category: String(payload.category || ''),
                original_name: String(payload.original_name || payload.stored_name || 'file'),
            }];
        },

        ensureOutputBucket(clientId) {
            if (!clientId) return;
            if (!this.outputs[clientId]) this.outputs[clientId] = [];
            if (!this.terminalViewStates) this.terminalViewStates = {};
            if (!this.terminalViewStates[clientId]) {
                this.terminalViewStates[clientId] = { follow: true, loading: false, hasOlder: false, hasNewer: false };
            }
        },

        ensureTerminalTaskStart(payload) {
            const clientId = String(payload?.client_id || '').trim();
            const taskId = String(payload?.task_id || '').trim();
            const metadata = payload?.metadata && typeof payload.metadata === 'object' ? payload.metadata : {};
            const incomingOperationId = String(metadata.operation_id || '').trim();
            if (!clientId || (!taskId && !incomingOperationId)) return incomingOperationId;

            // A local operation may already have a start line even before its HTTP response.
            const existing = (this.outputs[clientId] || []).find(line => line?.kind === 'command' && (
                (incomingOperationId && String(line.meta?.operation_id || line.meta?.operation?.operation_id || '') === incomingOperationId) ||
                (taskId && String(line.meta?.task_id || '') === taskId)
            ));
            if (existing) {
                return String(existing.meta?.operation_id || existing.meta?.operation?.operation_id || incomingOperationId);
            }
            // A very long task may push its start line out of the render window.
            // Its operation identity is still registered; avoid inventing a second start.
            const known = Object.values(this.terminalOperationRegistry).find(operation =>
                String(operation.client_id || '') === clientId && operation.startLineRecorded === true && (
                    (incomingOperationId && operation.operation_id === incomingOperationId) ||
                    (taskId && String(operation.task_id || '') === taskId)));
            if (known) return String(known.operation_id);

            const kind = metadata.quick_action === true ? 'alias'
                : metadata.script_run === true ? 'script' : 'command';
            const title = metadata.quick_action === true
                ? (metadata.quick_action_display_command || payload.command)
                : metadata.script_run === true
                    ? `[Run Script] ${metadata.script_run_name || payload.command || 'script'}`
                    : payload.command;
            const operation = createTerminalOperation({ kind, action: kind === 'script' ? 'run' : 'invoke',
                clientId, invocation: { input: String(payload.command || ''), task_id: taskId }, replay: null });
            if (incomingOperationId) operation.operation_id = incomingOperationId;
            this.appendOutput(clientId, `> ${String(title || `[Task] ${taskId}`).trim()}`, 'command', {
                operation, task_id: taskId,
            });
            return operation.operation_id;
        },

        // Stream batches share one history append and one visible-window commit.
        // Individual chunks still go through the existing JSON/operation parser.
        appendOutputBatch(clientId, entries) {
            if (!Array.isArray(entries) || !entries.length) return;
            const pending = [];
            this._terminalBatchLines = pending;
            try {
                for (const entry of entries) {
                    this.appendOutput(clientId, entry.text, entry.kind || '', entry.meta || {});
                }
            } finally {
                this._terminalBatchLines = null;
                if (pending.length) this.commitTerminalLines(clientId, pending, true);
            }
        },

        flushTerminalVisibleLines(clientId) {
            const queues = this._terminalRenderQueues;
            const pending = queues?.[clientId];
            if (!pending) return;
            delete queues[clientId];
            if (pending.frame !== null && typeof cancelAnimationFrame === 'function') {
                cancelAnimationFrame(pending.frame);
            }
            if (!pending.lines.length) return;
            const view = this.terminalViewStates[clientId];
            if (!view?.follow) {
                if (view) view.hasNewer = true;
                return;
            }
            this.outputs[clientId] = trimTerminalWindow(
                [...this.outputs[clientId], ...pending.lines], 'newer', TERMINAL_HISTORY);
            view.hasOlder = (this.outputs[clientId][0]?.__terminalSeq || 0) > 0;
            if (String(clientId) === String(this.selectedId)) this.scrollToBottom();
        },

        commitTerminalLines(clientId, lines, deferVisible = false) {
            if (!lines.length) return;
            if (!this._terminalHistory) {
                this.outputs[clientId].push(...lines);
                if (String(clientId) === String(this.selectedId)) this.scrollToBottom();
                return;
            }
            this._terminalHistory.append(clientId, lines);
            const view = this.terminalViewStates[clientId];
            if (!view.follow) {
                view.hasNewer = true;
                return;
            }
            if (!this._terminalRenderQueues) this._terminalRenderQueues = {};
            let queue = this._terminalRenderQueues[clientId];
            if (!queue) {
                queue = { lines: [], frame: null };
                this._terminalRenderQueues[clientId] = queue;
            }
            // A long burst only needs the latest display window. Historical rows
            // have already been persisted in full above.
            queue.lines = trimTerminalWindow([...queue.lines, ...lines], 'newer', TERMINAL_HISTORY);
            if (!deferVisible || typeof requestAnimationFrame !== 'function') {
                this.flushTerminalVisibleLines(clientId);
            } else if (queue.frame === null) {
                queue.frame = requestAnimationFrame(() => this.flushTerminalVisibleLines(clientId));
            }
        },

        appendOutput(clientId, text, kind = '', meta = null) {
            if (!clientId) return;
            this.ensureOutputBucket(clientId);

            if (!this._terminalJsonBuffers) {
                this._terminalJsonBuffers = {};
            }

            const inputMeta = meta && typeof meta === 'object' ? meta : {};
            const declared = inputMeta.operation;
            const operationId = String(declared?.operation_id || inputMeta.operation_id || inputMeta.metadata?.operation_id || '').trim();
            if (declared?.operation_id) {
                this.terminalOperationRegistry[operationId] = { ...declared, client_id: String(clientId), status: 'submitting' };
            }
            const associated = operationId && String(this.terminalOperationRegistry[operationId]?.client_id || '') === String(clientId)
                ? this.terminalOperationRegistry[operationId] : null;
            if (associated && inputMeta.event_type === 'output') associated.status = 'running';
            if (associated && inputMeta.event_type === 'completed') {
                associated.status = inputMeta.execution_status === 'cancelled' ? 'cancelled'
                    : inputMeta.execution_status === 'timed_out' ? 'timed_out'
                    : inputMeta.execution_success ? 'success' : 'error';
            }
            if (associated && inputMeta.event_type === 'submission_error') associated.status = 'error';
            if (associated && inputMeta.task_id) associated.task_id = String(inputMeta.task_id);

            // An event may arrive before its task submission response; the producer already
            // registered this UUID before sending the request. Never match by command text.
            const resolvedMeta = operationId
                ? { ...inputMeta, operation_id: operationId, ...(associated ? { operation: associated } : {}) }
                : inputMeta;
            const raw = String(text ?? '');
            if (associated && kind === 'command' && raw.startsWith('> ')) associated.startLineRecorded = true;
            const normalized = raw.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

            const added = [];
            const commit = () => {
                if (this._terminalHistory && added.length) {
                    const parts = added.flatMap(line => splitLongTerminalLine(line));
                    added.splice(0, added.length, ...parts);
                }
                if (inputMeta.foregroundTaskNotice || inputMeta.clientRevisionNotice) {
                    const noticeType = inputMeta.foregroundTaskNotice ? 'foreground' : 'revision';
                    this.setTerminalNotice(clientId, noticeType, added[added.length - 1] || null);
                    this.outputs[clientId].push(...added);
                    return;
                }
                if (this._terminalBatchLines) {
                    this._terminalBatchLines.push(...added);
                } else {
                    this.commitTerminalLines(clientId, added, inputMeta.event_type === 'output');
                }
            };

            if (this.isTerminalJsonText(normalized.trim())) {
                const line = this.buildTerminalOutputLine(normalized.trim(), kind, {
                    ...resolvedMeta,
                    forceJson: true,
                    jsonText: normalized.trim()
                });
                added.push(line);
                commit();
                return;
            }

            const segments = normalized.split('\n');
            const bufferKey = `${clientId}:${operationId || 'general'}`;

            const pushNormalLine = (segment, lineKind = kind, lineMeta = resolvedMeta) => {
                added.push(this.buildTerminalOutputLine(segment, lineKind, lineMeta));
            };

            const flushJsonBuffer = (buffer) => {
                const jsonText = this.tryParseTerminalJsonBuffer(buffer.lines);

                if (!jsonText) {
                    buffer.lines.forEach((line) => pushNormalLine(line, buffer.kind, buffer.meta));
                    return;
                }

                buffer.lines.forEach((line, index) => {
                    const isLast = index === buffer.lines.length - 1;
                    added.push(
                        this.buildTerminalOutputLine(line, buffer.kind || kind, {
                            ...(buffer.meta || {}),
                            forceJson: isLast,
                            jsonText: isLast ? jsonText : ''
                        })
                    );
                });
            };

            segments.forEach((segment) => {
                const trimmed = String(segment ?? '').trim();
                let buffer = this._terminalJsonBuffers[bufferKey];

                if (buffer) {
                    // Typed task output is data, even if it looks like a shell prompt
                    // or a historical [Command finished] line.
                    if (inputMeta.event_type !== 'output' && this.isTerminalCommandBoundaryLine(segment)) {
                        flushJsonBuffer(buffer);
                        this._terminalJsonBuffers[bufferKey] = null;
                        pushNormalLine(segment);
                        return;
                    }

                    buffer.lines.push(segment);
                    buffer.depth += this.calculateTerminalJsonDelta(segment);

                    if (buffer.depth <= 0) {
                        flushJsonBuffer(buffer);
                        this._terminalJsonBuffers[bufferKey] = null;
                    }
                    return;
                }

                if (this.isTerminalJsonStartLine(trimmed)) {
                    this._terminalJsonBuffers[bufferKey] = {
                        kind: kind || '',
                        meta: { ...resolvedMeta },
                        lines: [segment],
                        depth: this.calculateTerminalJsonDelta(segment)
                    };

                    if (this._terminalJsonBuffers[bufferKey].depth <= 0) {
                        flushJsonBuffer(this._terminalJsonBuffers[bufferKey]);
                        this._terminalJsonBuffers[bufferKey] = null;
                    }
                    return;
                }

                pushNormalLine(segment);
            });

            commit();
        },

        setTerminalNotice(clientId, type, line) {
            const notices = { ...(this.terminalNotices?.[clientId] || {}) };
            if (line) notices[type] = line;
            else delete notices[type];
            this.terminalNotices = { ...this.terminalNotices, [clientId]: notices };
        },
        getTerminalNotice(clientId, type) {
            return this.terminalNotices?.[clientId]?.[type] || null;
        },

        async initializeTerminalHistory() {
            const username = String(this.currentAuthUsername || '').trim();
            const tab = String(this.tabId || '').trim();
            if (!username || !tab) return;
            const store = new TerminalHistoryStore({
                scope: JSON.stringify([username, tab]),
                onError: error => {
                    console.error('Terminal history storage failed:', error);
                    ElMessage.error('Terminal history storage unavailable; recent output is kept in memory')
                },
            });
            try {
                await store.database();
                this._terminalHistory = store;
                for (const [clientId, lines] of Object.entries(this.outputs)) {
                    if (lines.length) store.append(clientId, lines);
                }
                await this.restoreTerminalViewport(this.selectedId);
            } catch (error) {
                console.warn('Terminal history unavailable; using in-memory output:', error);
                ElMessage.error('Browser history storage unavailable; output will remain in memory only');
            }
        },

        async restoreTerminalViewport(clientId, follow = true) {
            const id = String(clientId || '').trim();
            if (!id || !this._terminalHistory) return;
            this.ensureOutputBucket(id);
            const generation = this._terminalViewGeneration = (this._terminalViewGeneration || 0) + 1;
            const view = this.terminalViewStates[id];
            view.loading = true;
            try {
                const recent = await this._terminalHistory.readBefore(id, Infinity,
                    TERMINAL_HISTORY.initialLines, TERMINAL_HISTORY.initialBytes);
                if (generation !== this._terminalViewGeneration || id !== this.selectedId) return;
                this.outputs[id] = trimTerminalWindow([...recent,
                    ...Object.values(this.terminalNotices?.[id] || {})], 'newer', TERMINAL_HISTORY);
                view.follow = follow;
                view.hasOlder = (recent[0]?.__terminalSeq || 0) > 0;
                view.hasNewer = false;
                if (follow) this.scrollToBottom(true);
            } catch (error) {
                console.error('Unable to load Terminal history', error);
                ElMessage.error('Unable to load Terminal history');
            } finally {
                view.loading = false;
            }
        },

        async loadTerminalHistory(direction) {
            const id = String(this.selectedId || '').trim();
            if (!id || !this._terminalHistory) return;
            const view = this.terminalViewStates[id];
            if (!view || view.loading || (direction === 'older' && !view.hasOlder) ||
                (direction === 'newer' && !view.hasNewer)) return;
            if (direction !== 'older' && direction !== 'newer') return;
            const old = this.outputs[id] || [];
            const historyRows = old.filter(line => Number.isSafeInteger(line?.__terminalSeq));
            const notices = old.filter(line => line?.meta?.foregroundTaskNotice || line?.meta?.clientRevisionNotice);
            const cursor = direction === 'older'
                ? historyRows[0]?.__terminalSeq : historyRows[historyRows.length - 1]?.__terminalSeq;
            if (cursor === undefined) return;
            view.loading = true;
            const terminal = this.$refs.terminalOutputRef;
            const anchor = terminal?.captureScrollAnchor?.();
            try {
                // Reaching the top of the *rendered window* is ordinary pagination.
                // Never interpret it as a request to jump to the first stored record.
                const next = direction === 'older'
                    ? await this._terminalHistory.readBefore(id, cursor, TERMINAL_HISTORY.loadLines, TERMINAL_HISTORY.loadBytes)
                    : await this._terminalHistory.readAfter(id, cursor, TERMINAL_HISTORY.loadLines, TERMINAL_HISTORY.loadBytes);
                if (id !== this.selectedId || this.outputs[id] !== old) return;
                // Resolve the saved tail before touching the visible window. Awaiting an
                // IndexedDB request after the Vue state change lets the browser paint the
                // new (possibly final) rows before we can restore the reading position.
                const tail = direction === 'newer'
                    ? await this._terminalHistory.readBefore(id, Infinity, 1, Infinity) : null;
                if (id !== this.selectedId || this.outputs[id] !== old) return;
                const element = terminal?.terminalScrollElement?.();
                // A user can keep scrolling while IndexedDB reads. Preserve that movement
                // instead of restoring the viewport to the position from request start.
                const scrollDelta = element && anchor ? element.scrollTop - anchor.scrollTop : 0;
                const revealOlder = direction === 'older' && element?.scrollTop <= 1;
                if (direction === 'older') {
                    const merged = trimTerminalWindow([...next, ...historyRows], 'older', TERMINAL_HISTORY);
                    this.outputs[id] = [...merged, ...notices];
                    view.hasOlder = next.length > 0 && (next[0].__terminalSeq || 0) > 0;
                    view.hasNewer = merged.at(-1)?.__terminalSeq < historyRows.at(-1)?.__terminalSeq || view.hasNewer;
                } else {
                    const merged = trimTerminalWindow([...historyRows, ...next], 'newer', TERMINAL_HISTORY);
                    this.outputs[id] = [...merged, ...notices];
                    view.hasOlder = (merged[0]?.__terminalSeq || 0) > 0;
                    // Compare to the storage's current tail rather than assuming one batch reached it.
                    view.hasNewer = Boolean(tail.length && merged.at(-1)?.__terminalSeq < tail[0].__terminalSeq);
                }
                await this.$nextTick();
                if (id === this.selectedId) {
                    terminal?.restoreScrollAnchor?.(anchor, { scrollDelta, revealOlder });
                }
            } catch (error) {
                console.error('Unable to scroll Terminal history', error);
                ElMessage.error('Unable to load more Terminal history');
            } finally {
                view.loading = false;
            }
        },

        handleTerminalScroll({ atTop, atBottom, userInitiated = false } = {}) {
            const view = this.terminalViewStates[this.selectedId];
            if (!view) return;
            if (atTop && view.hasOlder && (userInitiated || !view.follow)) {
                if (userInitiated) view.follow = false;
                void this.loadTerminalHistory('older');
            } else if (atBottom && view.hasNewer) {
                void this.loadTerminalHistory('newer');
            } else if (atBottom && !view.hasNewer) {
                view.follow = true;
            } else if (!atBottom && userInitiated) {
                view.follow = false;
            }
        },

        async getCompleteTerminalHistory(clientId) {
            const id = String(clientId || this.selectedId || '').trim();
            if (this._terminalHistory) {
                const history = await this._terminalHistory.readAll(id);
                return [...history, ...Object.values(this.terminalNotices?.[id] || {})];
            }
            return this.outputs[id] || [];
        },

        async purgeTerminalHistory() {
            if (this._terminalHistory) await this._terminalHistory.clearScope();
        },

        clearOutput() {
            if (this.selectedId) {
                const clientId = this.selectedId;
                if (this._terminalRenderQueues?.[clientId]) {
                    const queued = this._terminalRenderQueues[clientId];
                    if (queued.frame !== null && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(queued.frame);
                    delete this._terminalRenderQueues[clientId];
                }
                this.outputs[clientId] = [];
                this.terminalNotices = { ...this.terminalNotices, [clientId]: {} };
                this.terminalViewStates[clientId] = { follow: true, loading: false, hasOlder: false, hasNewer: false };
                this._terminalViewGeneration = (this._terminalViewGeneration || 0) + 1;
                if (this._terminalJsonBuffers) {
                    for (const key of Object.keys(this._terminalJsonBuffers)) {
                        if (key.startsWith(`${clientId}:`)) delete this._terminalJsonBuffers[key];
                    }
                }
                if (this._terminalHistory) void this._terminalHistory.clear(clientId).catch(error => {
                    console.error('Unable to permanently clear Terminal history', error);
                    ElMessage.error('Unable to delete stored Terminal history');
                });
                delete this.terminalArtifactLinks[this.selectedId];
                for (const [id, operation] of Object.entries(this.terminalOperationRegistry)) {
                    if (String(operation.client_id) === String(this.selectedId)) delete this.terminalOperationRegistry[id];
                }
            }
        },

        scrollToBottom(force = false) {
            const view = this.terminalViewStates?.[this.selectedId];
            if (this._terminalHistory && view) {
                if (!force && !view.follow) return;
                if (force && view.hasNewer) { void this.restoreTerminalViewport(this.selectedId); return; }
                view.follow = true;
            }
            this.$nextTick(() => {
                const terminalOutput = this.$refs.terminalOutputRef;

                if (
                    terminalOutput &&
                    typeof terminalOutput.scrollToBottom === 'function'
                ) {
                    terminalOutput.scrollToBottom();
                }
            });
        },
    },

    computed: {
        currentOutputLines() {
            const clientId = this.selectedId;
            const notices = Object.values(this.terminalNotices?.[clientId] || {});
            const rendered = this.outputs[clientId] || [];
            return [...rendered, ...notices.filter(line =>
                !rendered.some(item => item?.meta?.foregroundTaskNotice === line?.meta?.foregroundTaskNotice &&
                    item?.meta?.clientRevisionNotice === line?.meta?.clientRevisionNotice &&
                    item?.text === line?.text))];
        },
        currentTerminalArtifactLinks() {
            return this.terminalArtifactLinks[this.selectedId] || [];
        },
    },
}