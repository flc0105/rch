// Only browser-to-Server uploads have an active XHR in this tab.
const activeBrowserUploads = new Map()

function normalizeHeaders(headers = {}) {
  return {...(headers || {})}
}

async function parseApiResponse(res, fallbackMessage) {
  const json = await res.json()
  if (!res.ok || json.code !== 0) {
    throw new Error(json.message || fallbackMessage)
  }
  return json.data || {}
}

export async function loadTransfers(tabId = '', { limit = 20, offset = 0, machineId = '' } = {}) {
  const headers = {}
  const normalizedTabId = String(tabId || '').trim()
  if (normalizedTabId) headers['X-Tab-Id'] = normalizedTabId
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (machineId) query.set('machine_id', machineId)
  const res = await fetch(`/api/transfers?${query}`, { headers })
  return parseApiResponse(res, 'Failed to load transfers')
}

export async function createBrowserUploadTransfer(payload = {}, headers = {}) {
  const res = await fetch('/api/transfers/browser-upload', {
    method: 'POST',
    headers: normalizeHeaders({
      'Content-Type': 'application/json',
      ...headers,
    }),
    body: JSON.stringify(payload || {}),
  })

  return parseApiResponse(res, 'Failed to initialize upload transfer')
}

export function buildBrowserUploadContentUrl(transfer = {}) {
  const path = String(transfer?.browser_upload_path || '').trim()
  if (!path) {
    throw new Error('Browser file transfer endpoint is unavailable')
  }

  // The upload shares the Web API origin; keep Vite's /api proxy in the request path.
  return path.startsWith('/') ? path : `/${path}`
}

// Shared browser -> Server -> Client upload path used by both remote file dialogs.
export async function uploadRemoteFileToClient({file, clientId, destinationPath, conflictPolicy = null, headers = {}, onStarted = null}) {
  const transfer = await createBrowserUploadTransfer({
    client_id: clientId,
    filename: file.name,
    total_bytes: file.size,
    destination_path: destinationPath,
    ...(conflictPolicy !== null ? { conflict_policy: conflictPolicy } : {}),
  }, headers)
  const transferId = String(transfer?.transfer_id || '').trim()
  let uploadXhr = null

  try {
    if (!transferId) throw new Error('Failed to initialize upload transfer')
    const token = String(transfer?.browser_upload_token || '').trim()
    if (!token) throw new Error('Browser file transfer token is unavailable')

    const url = buildBrowserUploadContentUrl(transfer)
    const response = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      uploadXhr = xhr
      activeBrowserUploads.set(transferId, xhr)
      xhr.open('POST', url, true)
      xhr.setRequestHeader('Content-Type', 'application/octet-stream')
      xhr.setRequestHeader('X-RCH-Transfer-Token', token)
      xhr.addEventListener('load', () => {
        let json = {}
        try {
          json = JSON.parse(xhr.responseText || '{}')
        } catch (error) {
          reject(new Error('Upload returned an invalid response'))
          return
        }
        if (xhr.status < 200 || xhr.status >= 300 || json.code !== 0) {
          reject(new Error(json.message || `Upload failed (${xhr.status || 'network error'})`))
          return
        }
        resolve(json)
      })
      xhr.addEventListener('error', () => reject(new Error('Browser upload connection failed')))
      xhr.addEventListener('abort', () => {
        const error = new Error('Browser upload was cancelled')
        error.name = 'AbortError'
        reject(error)
      })
      xhr.send(file)
      // Notify when the browser starts sending bytes, not after its upload finishes.
      if (typeof onStarted === 'function') {
        try { onStarted({ transferId }) } catch (error) { console.warn('Upload notification failed', error) }
      }
    })
    return response.data || {}
  } catch (error) {
    if (transferId && error?.name !== 'AbortError') {
      updateBrowserUploadTransfer(transferId, {
        state: 'failed',
        error: error.message || 'Browser upload failed',
      }, headers).catch(() => {})
    }
    throw error
  } finally {
    if (activeBrowserUploads.get(transferId) === uploadXhr) {
      activeBrowserUploads.delete(transferId)
    }
  }
}

export async function updateBrowserUploadTransfer(transferId, payload = {}, headers = {}) {
  const normalizedTransferId = String(transferId || '').trim()
  if (!normalizedTransferId) return null

  const res = await fetch(`/api/transfers/${encodeURIComponent(normalizedTransferId)}/browser-upload`, {
    method: 'PATCH',
    headers: normalizeHeaders({
      'Content-Type': 'application/json',
      ...headers,
    }),
    body: JSON.stringify(payload || {}),
  })

  return parseApiResponse(res, 'Failed to update upload transfer')
}


function buildTabHeaders(tabId = '', headers = {}) {
  const result = normalizeHeaders(headers)
  const normalizedTabId = String(tabId || '').trim()
  if (normalizedTabId) result['X-Tab-Id'] = normalizedTabId
  return result
}

export async function cancelTransfer(transferId, tabId = '') {
  const normalizedTransferId = String(transferId || '').trim()
  if (!normalizedTransferId) throw new Error('transfer_id is required')

  const res = await fetch(`/api/transfers/${encodeURIComponent(normalizedTransferId)}/cancel`, {
    method: 'POST',
    headers: buildTabHeaders(tabId),
  })
  const result = await parseApiResponse(res, 'Failed to cancel transfer')
  // The Server has accepted cancellation; also stop this tab's browser upload
  // so the caller's pending promise can settle and its Upload button unlocks.
  activeBrowserUploads.get(normalizedTransferId)?.abort()
  return result
}

export async function deleteRecentTransfer(transferId, tabId = '') {
  const normalizedTransferId = String(transferId || '').trim()
  if (!normalizedTransferId) throw new Error('transfer_id is required')

  const res = await fetch(`/api/transfers/${encodeURIComponent(normalizedTransferId)}`, {
    method: 'DELETE',
    headers: buildTabHeaders(tabId),
  })
  return parseApiResponse(res, 'Failed to delete transfer')
}

export async function clearRecentTransfers(tabId = '') {
  const res = await fetch('/api/transfers/recent', {
    method: 'DELETE',
    headers: buildTabHeaders(tabId),
  })
  return parseApiResponse(res, 'Failed to clear recent transfers')
}
