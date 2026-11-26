// Only browser-to-Server uploads have an active XHR in this tab.
const activeBrowserUploads = new Map()
const cancelledBatches = new Set()
const submittingBatches = new Set()
export function isBrowserUploadBatchCancelled(batchId) { return cancelledBatches.has(batchId) }

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

export async function startBrowserUploadBatch({ clientId, batchId, destinationPath,
  totalFiles, folderCount = 0 }, headers = {}) {
  const res = await fetch('/api/transfers/browser-upload-batch/start', {
    method: 'POST',
    headers: normalizeHeaders({ 'Content-Type': 'application/json', ...headers }),
    body: JSON.stringify({ client_id: clientId, batch_id: batchId,
      destination_path: destinationPath, total_files: totalFiles, folder_count: folderCount }),
  })
  const result = await parseApiResponse(res, 'Failed to initialize upload batch')
  submittingBatches.add(batchId)
  return result
}

export async function loadBatchTransfers(batchId, tabId = '') {
  const headers = buildTabHeaders(tabId)
  const res = await fetch(`/api/transfers/batches/${encodeURIComponent(batchId)}/items`, { headers })
  return parseApiResponse(res, 'Failed to load batch transfers')
}

export async function finalizeBrowserUploadBatch({ clientId, batchId, folderCount = 0, error = '' }, headers = {}) {
  const res = await fetch('/api/transfers/browser-upload-batch/finalize', {
    method: 'POST',
    headers: normalizeHeaders({ 'Content-Type': 'application/json', ...headers }),
    body: JSON.stringify({ client_id: clientId, batch_id: batchId, folder_count: folderCount, error }),
  })
  try { return await parseApiResponse(res, 'Failed to finalize upload batch') }
  finally { cancelledBatches.delete(batchId); submittingBatches.delete(batchId) }
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
export async function uploadRemoteFileToClient({file, clientId, destinationPath, conflictPolicy = null, headers = {}, onStarted = null, batchId = '', batchTotal = 0, batchIndex = 0}) {
  const transfer = await createBrowserUploadTransfer({
    client_id: clientId,
    filename: file.name,
    total_bytes: file.size,
    destination_path: destinationPath,
    ...(batchId ? { batch_id: batchId, batch_total: batchTotal, batch_index: batchIndex } : {}),
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
      activeBrowserUploads.set(transferId, { xhr, batchId })
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
    if (activeBrowserUploads.get(transferId)?.xhr === uploadXhr) {
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
  activeBrowserUploads.get(normalizedTransferId)?.xhr.abort()
  if (normalizedTransferId.startsWith('batch:')) {
    const batchId = normalizedTransferId.slice(6)
    if (submittingBatches.has(batchId)) cancelledBatches.add(batchId)
    for (const upload of activeBrowserUploads.values()) {
      if (upload.batchId === batchId) upload.xhr.abort()
    }
  }
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

export async function clearRecentTransfers(tabId = '', machineId = '') {
  const query = new URLSearchParams()
  if (machineId) query.set('machine_id', machineId)
  const url = query.size ? `/api/transfers/recent?${query}` : '/api/transfers/recent'
  const res = await fetch(url, {
    method: 'DELETE',
    headers: buildTabHeaders(tabId),
  })
  return parseApiResponse(res, 'Failed to clear recent transfers')
}
