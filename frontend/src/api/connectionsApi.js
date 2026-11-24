import { apiData, apiFetch, jsonRequestOptions } from './http.js'

export function listConnections() {
  return apiData('/api/connections', {}, [])
}

export function listSavedBindTargets() {
  return apiData('/api/connections/bind/targets', {}, [])
}

export function saveBindTarget(host, port, serverWebBaseUrl, name = '', targetId = '') {
  const path = targetId
    ? `/api/connections/bind/targets/${encodeURIComponent(targetId)}`
    : '/api/connections/bind/targets'
  return apiData(path, jsonRequestOptions(targetId ? 'PATCH' : 'POST', {
    host, port, server_web_base_url: serverWebBaseUrl, name,
  }), {})
}

export function removeSavedBindTarget(targetId) {
  return apiData(`/api/connections/bind/targets/${encodeURIComponent(targetId)}`, { method: 'DELETE' }, {})
}

export function getBindConnectionSettings() {
  return apiData('/api/connections/bind/settings', {}, {})
}

export function connectToClient(host, port, serverWebBaseUrl, name = '') {
  return apiData('/api/connections/bind/connect', jsonRequestOptions('POST', {
    host, port, server_web_base_url: serverWebBaseUrl, name,
  }), {})
}

export function disconnectConnection(clientId) {
  return apiData(`/api/connections/${encodeURIComponent(clientId)}/disconnect`, jsonRequestOptions('POST'), {})
}

export function killInstance(clientId) {
  return apiData(`/api/connections/${encodeURIComponent(clientId)}/kill-instance`, jsonRequestOptions('POST'), {})
}

export function reconnectConnection(clientId) {
  return apiData(`/api/connections/${encodeURIComponent(clientId)}/reconnect`, jsonRequestOptions('POST'), {})
}

export function reorderOnlineDevices(machineIds) {
  return apiFetch('/api/machines/order', jsonRequestOptions('PATCH', { machine_ids: machineIds }))
}

export function getConnectionRevisionStatus(clientId) {
  return apiData(`/api/connections/${encodeURIComponent(clientId)}/revision-status`, {}, {})
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

export function getMachineConnectionHistory(
  machineId, { limit = 20, offset = 0, clientIdSearch = '', integrity = '', launchMode = '', termination = '' } = {},
) {
  if (!machineId) return Promise.resolve({ sessions: [], has_more: false })
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (clientIdSearch.trim()) query.set('client_id_search', clientIdSearch.trim())
  if (integrity) query.set('integrity', integrity)
  if (launchMode) query.set('launch_mode', launchMode)
  if (termination) query.set('termination_reason', termination)
  return apiData(`/api/machines/${encodeURIComponent(machineId)}/connection-history?${query}`, {}, { sessions: [], has_more: false })
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

export function getConnectionTask(clientId) {
  return apiData(`/api/connections/${encodeURIComponent(clientId)}/task`, {}, { state: 'Idle' })
}

