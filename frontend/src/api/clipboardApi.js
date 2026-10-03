import { apiData, jsonRequestOptions } from './http.js'

function connectionPath(clientId, suffix) {
  return `/api/connections/${encodeURIComponent(clientId)}/clipboard/${suffix}`
}

export function getClipboardCapabilities(clientId) {
  return apiData(connectionPath(clientId, 'capabilities'), {}, {})
}

export function getRemoteClipboard(clientId) {
  return apiData(connectionPath(clientId, 'get'), { method: 'POST' }, {})
}

export function setRemoteClipboardText(clientId, text) {
  return apiData(
    connectionPath(clientId, 'set-text'),
    jsonRequestOptions('POST', { text }),
    {},
  )
}

export function setRemoteClipboardImage(clientId, file) {
  const form = new FormData()
  form.append('file', file, file?.name || 'clipboard.png')
  return apiData(connectionPath(clientId, 'set-image'), { method: 'POST', body: form }, {})
}

export function setRemoteClipboardArtifactFile(clientId, artifactId) {
  return apiData(
    connectionPath(clientId, 'set-artifact-file'),
    jsonRequestOptions('POST', { artifact_id: artifactId }),
    {},
  )
}

export function setRemoteClipboardFiles(clientId, items = []) {
  const form = new FormData()
  const uploads = []
  const entries = []
  const roots = []

  items.forEach((item) => {
    const kind = String(item?.kind || 'file')
    const rootName = String(item?.name || item?.file?.name || '').trim()
    if (!rootName) return

    roots.push(rootName)

    if (kind === 'directory') {
      const directories = Array.isArray(item.directories) ? item.directories : []
      const directoryFiles = Array.isArray(item.files) ? item.files : []

      directories.forEach((path) => {
        entries.push({ type: 'directory', path })
      })
      directoryFiles.forEach((entry) => {
        const file = entry?.file
        const path = String(entry?.relativePath || '').trim()
        if (!file || !path) return
        const uploadIndex = uploads.length
        uploads.push(file)
        entries.push({ type: 'file', path, upload_index: uploadIndex })
      })
      return
    }

    if (!item?.file) return
    const uploadIndex = uploads.length
    uploads.push(item.file)
    entries.push({ type: 'file', path: rootName, upload_index: uploadIndex })
  })

  uploads.forEach((file) => form.append('files', file, file?.name || 'clipboard_file'))
  form.append('manifest', JSON.stringify({ roots, entries }))
  return apiData(connectionPath(clientId, 'set-files'), { method: 'POST', body: form }, {})
}

export function downloadRemoteClipboardFile(clientId, path, headers = {}) {
  const url = `/api/connections/${encodeURIComponent(clientId)}/remote-files/download?path=${encodeURIComponent(path)}`
  return apiData(url, { method: 'POST', headers: { ...(headers || {}) } }, {})
}

export function downloadRemoteClipboardDirectory(clientId, path, headers = {}) {
  const url = `/api/connections/${encodeURIComponent(clientId)}/remote-files/download-zip`
  return apiData(
    url,
    jsonRequestOptions('POST', { paths: [path], archive_name: '' }, headers),
    {},
  )
}

export function downloadRemoteClipboardFiles(clientId, paths = [], headers = {}) {
  const url = `/api/connections/${encodeURIComponent(clientId)}/remote-files/download-zip`
  return apiData(
    url,
    jsonRequestOptions('POST', { paths, archive_name: '' }, headers),
    {},
  )
}
