// Only browser-to-Server uploads have an active XHR in this tab.
const activeBrowserUploads = new Map()
const cancelledBatches = new Set()
const submittingBatches = new Set()
export function isBrowserUploadBatchCancelled(batchId) { return cancelledBatches.has(batchId) }

function normalizeHeaders(headers = {}) {
  return {...(headers || {})}
}

async function parseApiResponse(res, fallbackMessage) {
  let json
  try { json = await res.json() } catch (_) { throw Object.assign(new Error(fallbackMessage), { uncertain: true }) }
  if (!json || typeof json !== 'object' || typeof json.code !== 'number') {
    throw Object.assign(new Error(fallbackMessage), { uncertain: true })
  }
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

async function submitUploadRegistration(url, options, fallbackMessage, canRecover) {
  const send = async () => {
    let res
    try { res = await fetch(url, options) }
    catch (error) { throw Object.assign(new Error(error.message || fallbackMessage), { uncertain: true }) }
    return parseApiResponse(res, fallbackMessage)
  }
  try { return await send() }
  catch (error) {
    if (!canRecover || !error.uncertain) throw error
    return send() // same identity and payload; Server returns the existing registration
  }
}

export async function createBrowserUploadTransfer(payload = {}, headers = {}) {
  return submitUploadRegistration('/api/transfers/browser-upload', {
    method: 'POST',
    headers: normalizeHeaders({
      'Content-Type': 'application/json',
      ...headers,
    }),
    body: JSON.stringify(payload || {}),
  }, 'Failed to initialize upload transfer', Boolean(payload.batch_id || headers['X-RCH-Operation-ID']))
}

export async function startBrowserUploadBatch({ clientId, batchId, destinationPath,
  files, directories }, headers = {}) {
  const result = await submitUploadRegistration('/api/transfers/browser-upload-batch/start', {
    method: 'POST',
    headers: normalizeHeaders({ 'Content-Type': 'application/json', ...headers }),
    body: JSON.stringify({ client_id: clientId, batch_id: batchId,
      destination_path: destinationPath, files, directories }),
  }, 'Failed to initialize upload batch', true)
  submittingBatches.add(batchId)
  return result
}

export async function loadBatchTransfers(batchId, tabId = '') {
  const headers = buildTabHeaders(tabId)
  const res = await fetch(`/api/transfers/batches/${encodeURIComponent(batchId)}/items`, { headers })
  return parseApiResponse(res, 'Failed to load batch transfers')
}

export async function finalizeBrowserUploadBatch({ clientId, batchId, folderCount = 0, error = '' }, headers = {}) {
  try {
    return await submitUploadRegistration('/api/transfers/browser-upload-batch/finalize', {
      method: 'POST',
      headers: normalizeHeaders({ 'Content-Type': 'application/json', ...headers }),
      body: JSON.stringify({ client_id: clientId, batch_id: batchId, folder_count: folderCount, error }),
    }, 'Failed to finalize upload batch', true)
  } finally { cancelledBatches.delete(batchId); submittingBatches.delete(batchId) }
}

export function buildBrowserUploadContentUrl(transfer = {}) {
  const path = String(transfer?.browser_upload_path || '').trim()
  if (!path) {
    throw new Error('Browser file transfer endpoint is unavailable')
  }

  // The upload shares the Web API origin; keep Vite's /api proxy in the request path.
  return path.startsWith('/') ? path : `/${path}`
}

// Browser byte intake is common; callers own destination execution and cancellation semantics.
export function uploadHttpBody(url, body, { headers = {}, signal, onProgress, onBodySent, onXhr, onStarted } = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const abortError = () => Object.assign(new Error('Browser upload was cancelled'), { name: 'AbortError' })
    const abort = () => xhr.abort()
    const settle = (fn, value) => { signal?.removeEventListener('abort', abort); fn(value) }
    if (signal?.aborted) { reject(abortError()); return }
    xhr.open('POST', url, true)
    for (const [key, value] of Object.entries(headers || {})) xhr.setRequestHeader(key, value)
    xhr.upload?.addEventListener('progress', event => onProgress?.(event.loaded, event.lengthComputable ? event.total : null))
    xhr.upload?.addEventListener('load', () => onBodySent?.())
    xhr.addEventListener('load', () => {
      let json
      try { json = JSON.parse(xhr.responseText || '{}') }
      catch (_) { settle(reject, Object.assign(new Error('Upload returned an invalid response'), { uncertain: true })); return }
      if (!json || typeof json !== 'object' || typeof json.code !== 'number') {
        settle(reject, Object.assign(new Error('Upload returned an invalid response'), { uncertain: true })); return
      }
      if (xhr.status < 200 || xhr.status >= 300 || json.code !== 0) {
        settle(reject, new Error(json.message || `Upload failed (${xhr.status || 'network error'})`)); return
      }
      settle(resolve, json)
    })
    xhr.addEventListener('error', () => settle(reject, Object.assign(new Error('Browser upload connection failed'), { uncertain: true })))
    xhr.addEventListener('abort', () => settle(reject, abortError()))
    signal?.addEventListener('abort', abort, { once: true })
    onXhr?.(xhr)
    try { xhr.send(body) } catch (error) { settle(reject, error); return }
    try { onStarted?.() } catch (error) { console.warn('Upload notification failed', error) }
  })
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
    if (transfer.accepted) return transfer
    const token = String(transfer?.browser_upload_token || '').trim()
    if (!token) throw new Error('Browser file transfer token is unavailable')

    const url = buildBrowserUploadContentUrl(transfer)
    const response = await uploadHttpBody(url, file, {
      headers: { 'Content-Type': 'application/octet-stream', 'X-RCH-Transfer-Token': token },
      onXhr: xhr => { uploadXhr = xhr; activeBrowserUploads.set(transferId, { xhr, batchId }) },
      onStarted: () => onStarted?.({ transferId }),
    })
    return response.data || {}
  } catch (error) {
    if (transferId && error?.uncertain) {
      // A lost response can occur after the Server has already queued the file.
      // Read status instead of resending bytes or overwriting a valid transfer.
      let status
      try {
        const res = await fetch(`/api/transfers/${encodeURIComponent(transferId)}/browser-upload`, { headers })
        status = await parseApiResponse(res, 'Failed to verify upload status')
      } catch (_) { /* The original transfer remains authoritative. */ }
      if (status?.state === 'completed' || (status?.state === 'running' && status?.accepted)) return status
      if (status?.state === 'cancelled') throw Object.assign(new Error('Browser upload was cancelled'), { name: 'AbortError' })
      if (status?.state === 'failed' || status?.state === 'interrupted') throw new Error(status.error || 'Upload failed')
      throw new Error(`${error.message}; upload status is uncertain. Check Transfers before retrying.`)
    }
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
