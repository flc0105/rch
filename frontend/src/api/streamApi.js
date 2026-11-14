// Browser events share the same lightweight WS server as PTY and Screen.
// Keep the named-event listener contract used by the existing UI.
export function webSocketUrl(path) {
  const url = new URL(path, window.location.href)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  // Vite forwards /ws to the configured Server WS port; production listens at HTTP port + 1.
  if (!import.meta.env?.DEV) {
    url.port = String(Number(window.location.port || (url.protocol === 'wss:' ? 443 : 80)) + 1)
  }
  return url.toString()
}

export function openWebEventStream(tabId) {
  const listeners = new Map()
  let socket = null
  let retry = null
  let stopped = false
  const resumeKey = `rch_command_stream_cursor:${tabId}`
  let resume = null
  try {
    resume = JSON.parse(sessionStorage.getItem(resumeKey) || 'null')
  } catch { /* Storage can be disabled; live events still work. */ }
  let cursor = Number.isSafeInteger(resume?.cursor) && resume.cursor >= 0 ? resume.cursor : null
  let epoch = typeof resume?.epoch === 'string' ? resume.epoch : ''
  const saveCursor = () => {
    if (cursor === null || !epoch) return
    try { sessionStorage.setItem(resumeKey, JSON.stringify({ cursor, epoch })) } catch {}
  }
  const stream = {
    onerror: null,
    readyState: WebSocket.CONNECTING,
    addEventListener(name, callback) {
      if (!listeners.has(name)) listeners.set(name, new Set())
      listeners.get(name).add(callback)
    },
    close() {
      stopped = true
      if (retry !== null) clearTimeout(retry)
      retry = null
      if (socket) socket.close()
      stream.readyState = WebSocket.CLOSED
    },
  }
  const dispatch = (name, event) => {
    for (const callback of listeners.get(name) || []) callback(event)
  }
  function connect() {
    if (stopped) return
    const resume = cursor !== null
      ? `&after=${encodeURIComponent(cursor)}&epoch=${encodeURIComponent(epoch)}` : ''
    const url = webSocketUrl(`/ws/events?tab_id=${encodeURIComponent(tabId)}${resume}`)
    stream.readyState = WebSocket.CONNECTING
    const ws = new WebSocket(url)
    socket = ws
    ws.onopen = () => {
      if (stopped || ws !== socket) return
      stream.readyState = WebSocket.OPEN
      dispatch('open', {})
    }
    ws.onmessage = (message) => {
      if (stopped || ws !== socket) return
      try {
        const item = JSON.parse(message.data || '{}')
        // The cursor follows delivery, not the socket open; failed WS sessions
        // can replay command output without a second HTTP transport.
        if (item.event === 'stream_cursor') {
          cursor = Number(item.cursor) || 0
          epoch = String(item.epoch || '')
          saveCursor()
          return
        }
        if (item.event) dispatch(item.event, {
          data: JSON.stringify(item.data ?? {}),
          lastEventId: String(item.id || ''),
        })
        // Persist after delivery so a reload resumes from the last handled
        // command event, not from the moment the socket was opened.
        if (item.cursor != null) {
          cursor = Number(item.cursor)
          saveCursor()
        }
      } catch (error) {
        console.warn('Invalid WebSocket event', error)
      }
    }
    ws.onerror = (event) => { if (!stopped) stream.onerror?.(event) }
    ws.onclose = () => {
      if (stopped || ws !== socket) return
      stream.readyState = WebSocket.CLOSED
      stream.onerror?.()
      retry = setTimeout(() => { retry = null; connect() }, 3000)
    }
  }
  connect()
  return stream
}
