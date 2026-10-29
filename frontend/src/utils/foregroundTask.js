export function normalizeForegroundTask(payload) {
  if (!payload || !['Running', 'Cancelling'].includes(payload.state)) return { state: 'Idle' }
  return { ...payload, state: payload.state }
}

export function shouldShowTaskNotice(task, localTaskId, pendingSubmission = null, tabId = '') {
  if (!task?.state || task.state === 'Idle') return false
  if (localTaskId && task.task_id === localTaskId) return false
  // Only hide the precise Web command being submitted by this live page.
  // A reused tab_id after refresh is never enough to suppress a warning.
  if (pendingSubmission && tabId && task.task_id && task.source === 'web' &&
      task.tab_id === tabId && task.command === pendingSubmission.command) return false
  return true
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
