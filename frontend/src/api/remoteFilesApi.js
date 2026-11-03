import { jsonRequestOptions } from './http.js'

const remoteFilesUrl = (clientId, suffix = '') =>
  `/api/connections/${encodeURIComponent(clientId)}/remote-files${suffix}`

const connectionUrl = (clientId, suffix) =>
  `/api/connections/${encodeURIComponent(clientId)}/${suffix}`

const webUiJson = (method, payload, headers = {}) =>
  jsonRequestOptions(method, payload, { ...headers, 'X-RCH-Origin': 'web_ui' })

// Return Response: callers retain their existing context/abort checks and error messages.
export function listRemoteDirectory(clientId, {
  path = '', page = 1, pageSize = 50, showHidden = false, search = '', recursive = false,
} = {}, options = {}) {
  const query = new URLSearchParams()
  if (path) query.set('path', path)
  query.set('page', String(page || 1))
  query.set('page_size', String(pageSize || 50))
  query.set('show_hidden', showHidden ? 'true' : 'false')
  if (search) {
    query.set('search', search)
    query.set('recursive', recursive ? 'true' : 'false')
  }
  return fetch(`${remoteFilesUrl(clientId)}?${query}`, options)
}

export function getRemoteSystemPaths(clientId) {
  return fetch(connectionUrl(clientId, 'system-paths'))
}

export function pasteRemoteFiles(clientId, payload) {
  return fetch(remoteFilesUrl(clientId, '/paste'), webUiJson('POST', payload))
}

export function createRemoteZip(clientId, payload) {
  return fetch(remoteFilesUrl(clientId, '/create-zip'), webUiJson('POST', payload))
}

export function extractRemoteZip(clientId, payload) {
  return fetch(remoteFilesUrl(clientId, '/extract-zip'), webUiJson('POST', payload))
}

export function inspectRemoteZip(clientId, path) {
  return fetch(remoteFilesUrl(clientId, '/zip-peek'), jsonRequestOptions('POST', { path }))
}

export function readRemoteZipEntry(clientId, path, entryName) {
  return fetch(remoteFilesUrl(clientId, '/zip-entry'),
    jsonRequestOptions('POST', { path, entry_name: entryName }))
}

export function makeRemoteDirectory(clientId, path) {
  return fetch(remoteFilesUrl(clientId, '/mkdir'), webUiJson('POST', { path }))
}

export function renameRemoteFile(clientId, oldPath, newName) {
  return fetch(remoteFilesUrl(clientId, '/rename'),
    webUiJson('POST', { old_path: oldPath, new_name: newName }))
}

export function downloadRemoteFile(clientId, path, headers = {}) {
  const query = new URLSearchParams({ path })
  return fetch(`${remoteFilesUrl(clientId, '/download')}?${query}`, {
    method: 'POST', headers: { ...headers, 'X-RCH-Origin': 'web_ui' },
  })
}

export function downloadRemoteZip(clientId, paths, headers = {}) {
  return fetch(remoteFilesUrl(clientId, '/download-zip'),
    webUiJson('POST', { paths, archive_name: '' }, headers))
}

export function deleteRemoteFile(clientId, path) {
  const query = new URLSearchParams({ path })
  return fetch(`${remoteFilesUrl(clientId)}?${query}`, {
    method: 'DELETE', headers: { 'X-RCH-Origin': 'web_ui' },
  })
}

export function deleteRemoteEntries(clientId, paths) {
  return fetch(remoteFilesUrl(clientId, '/batch'), webUiJson('DELETE', { paths }))
}
