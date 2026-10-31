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
    const url = webSocketUrl(`/ws/events?tab_id=${encodeURIComponent(tabId)}`)
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
        if (item.event) dispatch(item.event, {
          data: JSON.stringify(item.data ?? {}),
          lastEventId: String(item.id || ''),
        })
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
