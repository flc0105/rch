import { apiData, jsonRequestOptions } from './http.js'

const historyUrl = (machineId, suffix = '') =>
  `/api/machines/${encodeURIComponent(machineId)}/command-history${suffix}`

// Shared by command completion and task-result recovery.
export function getCommandHistory(machineId) {
  if (!machineId) return Promise.resolve([])
  return apiData(historyUrl(machineId), {}, [])
}

export function getCommandExecutionEntry(machineId, entryId) {
  return apiData(historyUrl(machineId, `/full/${encodeURIComponent(entryId)}`), {}, {})
}

// Dialog callers retain their response/error handling and request-generation guards.
export function fetchQuickCommandHistory(machineId) {
  return fetch(historyUrl(machineId))
}

export function fetchCommandActivities(machineId, { limit = 50, cursor = '', query = '', kind = '', errors = false } = {}) {
  const params = new URLSearchParams({ limit: String(limit) })
  if (cursor) params.set('cursor', cursor)
  if (query) params.set('query', query)
  if (kind) params.set('kind', kind)
  if (errors) params.set('errors', 'true')
  return fetch(`${historyUrl(machineId, '/full')}?${params.toString()}`)
}

export function pinHistoryCommand(machineId, command, isPinned) {
  return fetch(historyUrl(machineId, '/pin'),
    jsonRequestOptions('POST', { command, is_pinned: isPinned }))
}

export function movePinnedHistoryCommand(machineId, command, direction) {
  return fetch(historyUrl(machineId, '/pin/move'),
    jsonRequestOptions('POST', { command, direction }))
}

export function deleteCommandActivity(machineId, entryId) {
  return fetch(historyUrl(machineId, `/full/${encodeURIComponent(entryId)}`), { method: 'DELETE' })
}

export function clearQuickHistory(machineId, query = '') {
  const params = new URLSearchParams()
  if (query) params.set('query', query)
  const suffix = params.toString() ? `?${params.toString()}` : ''
  return fetch(historyUrl(machineId, suffix), { method: 'DELETE' })
}

export function clearCommandActivities(machineId, { kind = '', errors = false, query = '' } = {}) {
  const params = new URLSearchParams()
  if (kind) params.set('kind', kind)
  if (errors) params.set('errors', 'true')
  if (query) params.set('query', query)
  const suffix = params.toString() ? `?${params.toString()}` : ''
  return fetch(historyUrl(machineId, `/full${suffix}`), { method: 'DELETE' })
}
