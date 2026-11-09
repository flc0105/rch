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
            const normalized = raw.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

            if (this.isTerminalJsonText(normalized.trim())) {
                const line = this.buildTerminalOutputLine(normalized.trim(), kind, {
                    ...resolvedMeta,
                    forceJson: true,
                    jsonText: normalized.trim()
                });
                this.outputs[clientId].push(line);
                this.scrollToBottom();
                return;
            }

            const segments = normalized.split('\n');
            const bufferKey = `${clientId}:${operationId || 'general'}`;

            const pushNormalLine = (segment, lineKind = kind, lineMeta = resolvedMeta) => {
                this.outputs[clientId].push(
                    this.buildTerminalOutputLine(segment, lineKind, lineMeta)
                );
            };

            const flushJsonBuffer = (buffer) => {
                const jsonText = this.tryParseTerminalJsonBuffer(buffer.lines);

                if (!jsonText) {
                    buffer.lines.forEach((line) => pushNormalLine(line, buffer.kind, buffer.meta));
                    return;
                }

                buffer.lines.forEach((line, index) => {
                    const isLast = index === buffer.lines.length - 1;
                    this.outputs[clientId].push(
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

            this.scrollToBottom();
        },

        clearOutput() {
            if (this.selectedId) {
                this.outputs[this.selectedId] = [];
                delete this.terminalArtifactLinks[this.selectedId];
                for (const [id, operation] of Object.entries(this.terminalOperationRegistry)) {
                    if (String(operation.client_id) === String(this.selectedId)) delete this.terminalOperationRegistry[id];
                }
            }
        },

        scrollToBottom() {
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
            return this.outputs[this.selectedId] || [];
        },
        currentTerminalArtifactLinks() {
            return this.terminalArtifactLinks[this.selectedId] || [];
        },
    },
}