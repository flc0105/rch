import { apiData, jsonRequestOptions } from './http.js'

export const DEFAULT_SERVER_PREFERENCES = Object.freeze({
  ask_on_conflict: false,
  preview_text_max_bytes: 512 * 1024,
  log_viewer_max_bytes: 512 * 1024,
})

const PATH = '/api/server/preferences'
export const loadServerPreferences = () => apiData(PATH, {}, DEFAULT_SERVER_PREFERENCES)
export const saveServerPreferences = (preferences) =>
  apiData(PATH, jsonRequestOptions('PUT', preferences), DEFAULT_SERVER_PREFERENCES)
