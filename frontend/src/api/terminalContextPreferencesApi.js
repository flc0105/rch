import { apiData, jsonRequestOptions } from './http.js'

export function loadTerminalContextPreferences() {
  return apiData('/api/terminal/context-preferences', {}, { field_ids: [] })
}

export function saveTerminalContextPreferences(payload = {}) {
  return apiData(
    '/api/terminal/context-preferences',
    jsonRequestOptions('PUT', payload),
    { field_ids: [] },
  )
}
