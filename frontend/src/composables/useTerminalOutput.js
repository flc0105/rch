import { isJsonContainerText, isJsonStartLine, parseJsonLines, jsonBracketDelta } from '../utils/terminalJson.js'
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
                kind: kind || this.inferLineKind(segment),
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

        ensureOutputBucket(clientId) {
            if (!clientId) return;
            if (!this.outputs[clientId]) this.outputs[clientId] = [];
        },

        appendOutput(clientId, text, kind = '', meta = null) {
            if (!clientId) return;
            this.ensureOutputBucket(clientId);

            if (!this._terminalJsonBuffers) {
                this._terminalJsonBuffers = {};
            }

            const raw = String(text ?? '');
            const normalized = raw.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

            if (this.isTerminalJsonText(normalized.trim())) {
                const line = this.buildTerminalOutputLine(normalized.trim(), kind, {
                    ...(meta || {}),
                    forceJson: true,
                    jsonText: normalized.trim()
                });
                this.outputs[clientId].push(line);
                this.scrollToBottom();
                return;
            }

            const segments = normalized.split('\n');

            const pushNormalLine = (segment, lineKind = kind, lineMeta = meta) => {
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
                let buffer = this._terminalJsonBuffers[clientId];

                if (buffer) {
                    if (this.isTerminalCommandBoundaryLine(segment)) {
                        flushJsonBuffer(buffer);
                        this._terminalJsonBuffers[clientId] = null;
                        pushNormalLine(segment);
                        return;
                    }

                    buffer.lines.push(segment);
                    buffer.depth += this.calculateTerminalJsonDelta(segment);

                    if (buffer.depth <= 0) {
                        flushJsonBuffer(buffer);
                        this._terminalJsonBuffers[clientId] = null;
                    }
                    return;
                }

                if (this.isTerminalJsonStartLine(trimmed)) {
                    this._terminalJsonBuffers[clientId] = {
                        kind: kind || '',
                        meta: meta ? {...meta} : null,
                        lines: [segment],
                        depth: this.calculateTerminalJsonDelta(segment)
                    };

                    if (this._terminalJsonBuffers[clientId].depth <= 0) {
                        flushJsonBuffer(this._terminalJsonBuffers[clientId]);
                        this._terminalJsonBuffers[clientId] = null;
                    }
                    return;
                }

                pushNormalLine(segment);
            });

            this.scrollToBottom();
        },

        clearOutput() {
            if (this.selectedId) this.outputs[this.selectedId] = [];
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
    },
}