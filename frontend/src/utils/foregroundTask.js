export function normalizeForegroundTask(payload) {
  if (!payload || !['Running', 'Cancelling'].includes(payload.state)) return { state: 'Idle' }
  return { ...payload, state: payload.state }
}

// ClientSession tasks are not always Web Tasks with a task_id. Their started_at
// stays stable when the remote command ID or cancellation state changes.
export function foregroundTaskNoticeKey(task) {
  if (!['Running', 'Cancelling'].includes(task?.state)) return ''
  if (task.task_id) return `task:${task.task_id}`
  if (!task.started_at) return ''
  return `started:${task.started_at}:${task.task_type || ''}:${task.source || ''}:${task.command || ''}`
}

export function shouldShowTaskNotice(task, admittedKey = '') {
  return !!admittedKey && foregroundTaskNoticeKey(task) === admittedKey
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
