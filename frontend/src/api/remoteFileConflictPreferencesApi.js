import { apiData, jsonRequestOptions } from './http.js'

const PATH = '/api/remote-files/conflict-preferences'
export const loadRemoteFileConflictPreferences = () => apiData(PATH, {}, { ask_on_conflict: false })
export const saveRemoteFileConflictPreferences = (payload) =>
  apiData(PATH, jsonRequestOptions('PUT', payload), { ask_on_conflict: false })
