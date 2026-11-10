import { jsonRequestOptions } from './http.js'

const artifactUrl = (artifactId, suffix = '') =>
  `/api/artifacts/${encodeURIComponent(artifactId)}${suffix}`

// Return Response to retain the callers' existing validation and UI feedback.
export function listArtifacts() {
  return fetch('/api/artifacts')
}

export function createArtifactFolder(scope, name, parentId = '') {
  return fetch('/api/artifacts/folders', jsonRequestOptions('POST', { scope, name, parent_id: parentId }))
}

export function renameArtifactFolder(folderId, name) {
  return fetch(`/api/artifacts/folders/${encodeURIComponent(folderId)}/rename`,
    jsonRequestOptions('POST', { name }))
}

export function deleteArtifactFolder(folderId) {
  return fetch(`/api/artifacts/folders/${encodeURIComponent(folderId)}`, { method: 'DELETE' })
}

export function moveArtifactToFolder(artifactId, folderId) {
  return fetch(artifactUrl(artifactId, '/move'), jsonRequestOptions('POST', { folder_id: folderId }))
}

export function uploadArtifact(formData, headers) {
  return fetch('/api/files/upload', {
    method: 'POST',
    ...(headers === undefined ? {} : { headers }),
    body: formData,
  })
}

export function renameArtifact(artifactId, name, headers = {}) {
  return fetch(artifactUrl(artifactId, '/rename'),
    jsonRequestOptions('POST', { name, original_name: name }, headers))
}

export function sendArtifactToClient(artifactId, clientId, targetPath, headers = {}, conflictPolicy = 'stop') {
  return fetch(artifactUrl(artifactId, '/send-to-client'),
    jsonRequestOptions('POST', { client_id: clientId, target_path: targetPath, conflict_policy: conflictPolicy }, headers))
}

export function deleteArtifact(artifactId) {
  return fetch(artifactUrl(artifactId), { method: 'DELETE' })
}

export function clearArtifacts(type, machineId = '', scope = '', folderId = '') {
  const payload = { type, machine_id: machineId }
  if (scope) payload.scope = scope
  if (folderId) payload.folder_id = folderId
  return fetch('/api/artifacts/clear', jsonRequestOptions('POST', payload))
}

export function previewArtifact(artifactId) {
  return fetch(artifactUrl(artifactId, '/preview'))
}

export function inspectArtifactZip(artifactId) {
  return fetch(artifactUrl(artifactId, '/zip-peek'))
}

export function readArtifactZipEntry(artifactId, entryName) {
  return fetch(artifactUrl(artifactId, '/zip-entry'),
    jsonRequestOptions('POST', { entry_name: entryName }))
}

export function saveArtifactContent(artifactId, content, encoding) {
  return fetch(artifactUrl(artifactId, '/content'),
    jsonRequestOptions('PUT', { content, encoding }))
}

export function saveCommandOutputArtifact(payload) {
  return fetch('/api/artifacts/command-output/save', jsonRequestOptions('POST', payload))
}

export function savePreviewToSaved(artifactId, folderId = '') {
  return fetch(artifactUrl(artifactId, '/save-to-saved'),
    jsonRequestOptions('POST', { folder_id: folderId }))
}
