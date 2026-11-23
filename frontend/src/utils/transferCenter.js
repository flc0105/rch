// Mirror the official Transfer lifecycle eligibility contract used by SSE actions.
export function canUseTransferArtifact(transfer) {
  return transfer?.direction === 'client_to_server'
    && transfer?.state === 'completed'
    && Boolean(String(transfer?.artifact_id || '').trim())
}

export function transferArtifactDownloadUrl(transfer) {
  if (!canUseTransferArtifact(transfer)) return ''
  return `/api/artifacts/${encodeURIComponent(transfer.artifact_id)}/download`
}

export function transferDisplayName(transfer) {
  const name = String(transfer?.filename || '').trim().replaceAll('\\', '/')
  return name.split('/').filter(Boolean).pop() || 'File transfer'
}
