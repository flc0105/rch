// An operation UUID is assigned before HTTP submission and echoed by task SSE.
// This permits strict matching even when two identical commands run concurrently
// or SSE reaches the browser before the HTTP response.
export function createTerminalTaskCapture() {
  const sessions = new Set()

  function matches(entry, payload) {
    if (!payload?.task_id || String(payload.client_id || '') !== entry.clientId) return false
    const operationId = String(payload.metadata?.operation_id || payload.operation_id || '')
    if (entry.operationId) return operationId === entry.operationId
      && (!entry.taskId || String(payload.task_id) === entry.taskId)
    return !!entry.taskId && String(payload.task_id) === entry.taskId
  }

  function deliver(entry, kind, payload) {
    if (kind === 'result') entry.onResult?.(payload)
    else {
      entry.onComplete?.(payload)
      sessions.delete(entry)
    }
  }

  return {
    begin({ clientId, operationId = '', suppress = false, onResult, onComplete }) {
      const entry = {
        clientId: String(clientId), operationId: String(operationId), suppress,
        onResult, onComplete, taskId: '', pending: [],
      }
      sessions.add(entry)
      return {
        bind(taskId) {
          const id = String(taskId || '')
          if (!id || !sessions.has(entry)) return false
          entry.taskId = id
          const buffered = entry.pending
          entry.pending = []
          for (const { kind, payload } of buffered) {
            if (String(payload.task_id) === id) deliver(entry, kind, payload)
          }
          return true
        },
        cancel() { sessions.delete(entry) },
      }
    },

    route(kind, payload = {}) {
      // Prefer a bound task, but do not allow a different operation's ID to
      // intercept it. A pending operation only buffers its own UUID.
      for (const entry of sessions) {
        if (!entry.taskId || !matches(entry, payload)) continue
        deliver(entry, kind, payload)
        return entry.suppress
      }
      for (const entry of sessions) {
        if (entry.taskId || !matches(entry, payload)) continue
        entry.pending.push({ kind, payload })
        return entry.suppress
      }
      return false
    },
  }
}
