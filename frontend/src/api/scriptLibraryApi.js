import { jsonRequestOptions } from './http.js'

// Return the native Response so the dialog retains its existing UI error handling.
export function getScriptCatalog() {
  return fetch('/api/scripts/catalog')
}

export function runLibraryScript(clientId, payload, headers = {}) {
  return fetch(`/api/connections/${encodeURIComponent(clientId)}/scripts/run`,
    jsonRequestOptions('POST', payload, headers))
}

export function createScriptFolder(directory) {
  return fetch('/api/scripts/folders', jsonRequestOptions('POST', { directory }))
}

export function renameScriptFolder(directory, newDirectory) {
  return fetch('/api/scripts/folders/rename',
    jsonRequestOptions('POST', { directory, new_directory: newDirectory }))
}

export function deleteScriptFolder(directory) {
  return fetch('/api/scripts/folders', jsonRequestOptions('DELETE', { directory }))
}

export function renameLibraryScript(name, newName) {
  return fetch('/api/scripts/rename', jsonRequestOptions('POST', { name, new_name: newName }))
}

export function uploadLibraryScript(formData) {
  return fetch('/api/scripts/upload', { method: 'POST', body: formData })
}

export function deleteLibraryScript(name) {
  return fetch('/api/scripts/delete', jsonRequestOptions('DELETE', { name }))
}
