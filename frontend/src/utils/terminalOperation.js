// A browser operation is an identity/presentation contract, not a remote shell command.
// The server echoes its UUID in WebTask SSE metadata and never executes it.
export function createTerminalOperation({ kind, action, clientId, invocation = {}, replay = null, presentation = 'terminal' }) {
  const operation_id = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `00000000-0000-4000-8000-${Array.from({length: 12}, () => Math.floor(Math.random() * 16).toString(16)).join('')}`
  return {
    operation_id, client_id: String(clientId || ''), kind, action, origin: 'web_ui',
    presentation, invocation: { ...invocation }, replay: replay ? { ...replay } : null,
  }
}

export function operationHeaders(operation, headers = {}) {
  return { ...headers, 'X-RCH-Operation-ID': operation.operation_id }
}

export function operationFromLine(line) {
  return line?.meta?.operation || null
}

export function getTerminalReplayAction(operation) {
  const replay = operation?.replay
  if (!replay || typeof replay !== 'object') return null
  if (replay.type === 'command') {
    const command = String(replay.command || '').trim()
    return command ? { type: 'command', command } : null
  }
  if (replay.type === 'script') {
    const script_name = String(replay.script_name || '').trim()
    if (!script_name) return null
    return { type: 'script', script_name,
      script_path: String(replay.script_path || ''),
      script_display_name: String(replay.script_display_name || ''),
      ...(replay.execution_mode ? { execution_mode: replay.execution_mode } : {}),
      ...(replay.output_mode ? { output_mode: replay.output_mode } : {}),
      params: replay.params && typeof replay.params === 'object' && !Array.isArray(replay.params)
        ? { ...replay.params } : {} }
  }
  if (replay.type === 'alias' && operation.kind === 'alias') {
    const alias = String(replay.alias || '').trim()
    const platform = String(replay.platform || '').trim()
    if (!alias || !platform || !Array.isArray(replay.arguments) ||
        !replay.arguments.every(value => typeof value === 'string')) return null
    return { type: 'alias', alias, platform, arguments: [...replay.arguments] }
  }
  return null
}
