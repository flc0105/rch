// Associate SSE events with an existing task_id without adding UI fields to the command API.
// A submission may complete before HTTP returns; retain just its interim events until bind().
export function createTerminalTaskCapture() {
  const sessions = new Set()

  function matches(entry, payload) {
    if (!payload?.task_id || String(payload.client_id || '') !== entry.clientId) return false
    if (entry.taskId) return String(payload.task_id) === entry.taskId
    // When the task ID is still pending, only capture same-command events for
    // dialog actions; reruns may be scripts, whose SSE command text differs.
    return !entry.suppress || String(payload.command || '') === entry.command
  }

  function deliver(entry, kind, payload) {
    if (kind === 'result') entry.onResult?.(payload)
    else {
      entry.onComplete?.(payload)
      sessions.delete(entry)
    }
  }

  return {
    begin({ clientId, command = '', suppress = false, onResult, onComplete }) {
      const entry = {
        clientId: String(clientId), command: String(command), suppress,
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
      // Prefer an already-bound task. A different pending submission must not
      // intercept or mask events for a task whose ID is already established.
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
