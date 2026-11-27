const STORAGE_KEY = 'rat_web_tab_id'
const CLAIM_PREFIX = 'rch-web-tab:'

function newTabId() {
  return globalThis.crypto?.randomUUID?.() || `tab_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

// A copied tab can inherit sessionStorage. A live document owns its ID, and
// only a reload/history navigation is eligible to reclaim a previous ID.
export async function claimTabIdentity() {
  let previous = ''
  try {
    const navigation = performance.getEntriesByType('navigation')[0]?.type
    if (navigation === 'reload' || navigation === 'back_forward') {
      previous = String(sessionStorage.getItem(STORAGE_KEY) || '').trim()
    }
  } catch { /* Storage can be unavailable. */ }

  const locks = globalThis.navigator?.locks
  let id = previous || newTabId()
  let release = () => {}
  let claimed = false
  if (locks?.request) {
    try {
      const claim = candidate => new Promise((resolve, reject) => {
        locks.request(CLAIM_PREFIX + candidate, { ifAvailable: true }, lock => {
          if (!lock) { resolve(false); return }
          return new Promise(done => { release = done; resolve(true) })
        }).catch(reject)
      })
      while (!(await claim(id))) id = newTabId()
      claimed = true
    } catch { /* Non-secure origins may not offer Web Locks. */ }
  }

  if (!claimed && typeof BroadcastChannel === 'function') {
    // Non-secure HTTP still supports BroadcastChannel. Existing documents
    // answer ownership probes; a collision uses a new history/stream scope.
    let channel
    try {
      channel = new BroadcastChannel(CLAIM_PREFIX + id)
      if (previous) {
        const occupied = await new Promise(resolve => {
          const timer = setTimeout(() => resolve(false), 150)
          channel.onmessage = ({ data }) => {
            if (data === 'probe') channel.postMessage('occupied')
            if (data === 'occupied') { clearTimeout(timer); resolve(true) }
          }
          channel.postMessage('probe')
        })
        if (occupied) {
          channel.close()
          id = newTabId()
          channel = new BroadcastChannel(CLAIM_PREFIX + id)
        }
      }
      channel.onmessage = ({ data }) => { if (data === 'probe') channel.postMessage('occupied') }
      release = () => channel.close()
      claimed = true
    } catch { channel?.close() }
  }
  // Without an ownership primitive, prefer a fresh scope to sharing a writer.
  if (!claimed) id = newTabId()
  try { sessionStorage.setItem(STORAGE_KEY, id) } catch {}
  return { id, release }
}
