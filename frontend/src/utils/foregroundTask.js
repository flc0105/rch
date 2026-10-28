export function normalizeForegroundTask(payload) {
  if (!payload || !['Running', 'Cancelling'].includes(payload.state)) return { state: 'Idle' }
  return { ...payload, state: payload.state }
}

export function shouldShowTaskNotice(task, localTaskId) {
  return task?.state !== 'Idle' && !!task?.state && (
    !localTaskId || task.task_id !== localTaskId
  )
}

export function formatTaskTime(startedAt, now = Date.now()) {
  const ms = Date.parse(startedAt || '')
  if (!Number.isFinite(ms)) return '-'
  const elapsed = Math.max(0, Math.floor((now - ms) / 1000))
  const hours = Math.floor(elapsed / 3600)
  const minutes = Math.floor((elapsed % 3600) / 60)
  const seconds = elapsed % 60
  return `${hours ? `${hours}h ` : ''}${minutes}m ${seconds}s`
}
