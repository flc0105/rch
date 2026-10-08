import { apiData, apiFetch, jsonRequestOptions } from './http.js'

export function listConnections() {
  return apiData('/api/connections', {}, [])
}

export function verifyHiddenDevicesPassword(password = '') {
  return apiData(
    '/api/connections/hidden-devices/verify',
    jsonRequestOptions('POST', { password }),
    { required: false, verified: false },
  )
}

export function getConnectionRevisionStatus(clientId) {
  return apiData(`/api/connections/${encodeURIComponent(clientId)}/revision-status`, {}, {})
}

export function killConnection(clientId) {
  return apiFetch(`/api/connections/${encodeURIComponent(clientId)}/kill`, {
    method: 'POST',
  })
}

export function removeConnection(clientId, payload = {}) {
  return apiFetch(`/api/connections/${encodeURIComponent(clientId)}`, {
    ...jsonRequestOptions('DELETE', payload),
    method: 'DELETE',
  })
}


export function updateConnectionDeviceViewPrefs(payload = {}) {
  return apiData(
    '/api/connections/device-view-prefs',
    jsonRequestOptions('PATCH', payload),
    {},
  )
}

export function sendCommand(clientId, command, headers = {}) {
  return apiData(
    `/api/connections/${encodeURIComponent(clientId)}/command`,
    jsonRequestOptions('POST', { command }, headers),
    {},
  )
}

export function getWatchdogStatus(clientId) {
  return apiData(`/api/connections/${encodeURIComponent(clientId)}/watchdog`, {}, {})
}

export function updateRuntimeConfig(clientId, key, value) {
  return apiData(
    `/api/connections/${encodeURIComponent(clientId)}/runtime-config/${encodeURIComponent(key)}`,
    jsonRequestOptions('PUT', { value }),
    {},
  )
}

export function getHttpControlActions() {
  return apiData('/api/httpctl/actions', {}, [])
}

export function queueHttpControlAction(clientId, action) {
  return apiData(
    `/api/connections/${encodeURIComponent(clientId)}/control`,
    jsonRequestOptions('POST', { command: action }),
    {},
  )
}

export function getCommandCandidates(clientId) {
  return apiData(`/api/connections/${encodeURIComponent(clientId)}/command-candidates`, {}, [])
}

export function getCommandCompletions(clientId, payload = {}) {
  return apiData(
    `/api/connections/${encodeURIComponent(clientId)}/command-completions`,
    jsonRequestOptions('POST', payload),
    { items: [] },
  )
}

export function getCommandHistory(machineId) {
  if (!machineId) return Promise.resolve([])
  return apiData(`/api/machines/${encodeURIComponent(machineId)}/command-history`, {}, [])
}

export function getMachineConnectionHistory(machineId) {
  if (!machineId) return Promise.resolve({ sessions: [] })
  return apiData(`/api/machines/${encodeURIComponent(machineId)}/connection-history`, {}, { sessions: [] })
}

export function getMachineConnectionCommands(machineId, clientId, params = {}) {
  if (!machineId || !clientId) {
    return Promise.resolve({ items: [], next_cursor: '', has_more: false, total_count: 0 })
  }

  const query = new URLSearchParams({ limit: String(params.limit || 50) })
  if (params.cursor) query.set('cursor', String(params.cursor))

  return apiData(
    `/api/machines/${encodeURIComponent(machineId)}/connection-history/${encodeURIComponent(clientId)}/commands?${query.toString()}`,
    {},
    { items: [], next_cursor: '', has_more: false, total_count: 0 },
  )
}
