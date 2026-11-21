const progressMarkers = { info: '[*]', success: '[+]', warning: '[!]', error: '[-]' }

export function activityOutputRecords(result, {
  terminal = false, recordedAt = [], outputTexts = [], newestFirst = false, limit = Infinity,
} = {}) {
  const packets = Array.isArray(result) ? result : []
  const records = []
  for (let offset = 0; offset < packets.length && records.length < limit; offset += 1) {
    const index = newestFirst ? packets.length - 1 - offset : offset
    const event = packets[index]
    let text = typeof outputTexts[index] === 'string' ? outputTexts[index] : (event.message || '')
    if (!text && typeof outputTexts[index] !== 'string' && 'data' in event && event.event_type !== 'started') {
      text = JSON.stringify(event.data, null, terminal ? 2 : undefined)
    }
    if (!text) continue
    if (event.event_type === 'progress' && event.message && progressMarkers[event.level]
      && !/^\s*\[(?:\*|\+|!|-)\]/.test(text)) {
      text = `${progressMarkers[event.level]} ${text}`
    }
    const failed = event.event_type === 'completed' && !['success', 'partial'].includes(event.status)
    records.push({ seq: index + 1, status: failed ? 0 : 1, text, created_at: recordedAt[index] })
  }
  return records
}
