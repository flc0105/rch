import { TERMINAL_HISTORY } from '../data/terminalHistoryConfig.js'

const DATABASE_NAME = 'rch-terminal-history'
const DATABASE_VERSION = 1
const MAX_CHUNK = Number.MAX_SAFE_INTEGER

function requestResult(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('IndexedDB request failed'))
  })
}
function transactionDone(transaction) {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve()
    transaction.onabort = () => reject(transaction.error || new Error('IndexedDB transaction aborted'))
    transaction.onerror = () => reject(transaction.error || new Error('IndexedDB transaction failed'))
  })
}
function openDatabase(factory) {
  return new Promise((resolve, reject) => {
    const request = factory.open(DATABASE_NAME, DATABASE_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains('chunks')) db.createObjectStore('chunks', { keyPath: ['scope', 'client', 'chunk'] })
      if (!db.objectStoreNames.contains('meta')) db.createObjectStore('meta', { keyPath: ['scope', 'client'] })
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('Unable to open terminal history'))
    request.onblocked = () => reject(new Error('Terminal history database upgrade is blocked by another tab'))
  })
}
const byteSizeCache = new WeakMap()
const textEncoder = typeof TextEncoder !== 'undefined' ? new TextEncoder() : null
export function terminalLineBytes(line) {
  if (line && typeof line === 'object' && byteSizeCache.has(line)) return byteSizeCache.get(line)
  const text = String(line?.text ?? '')
  const bytes = textEncoder ? textEncoder.encode(text).length : text.length * 2
  if (line && typeof line === 'object') byteSizeCache.set(line, bytes)
  return bytes
}
export function splitLongTerminalLine(line, limit = TERMINAL_HISTORY.displaySegmentChars) {
  const value = String(line?.text ?? '')
  if (value.length <= limit) return [line]
  const parts = []
  for (let offset = 0; offset < value.length;) {
    let end = Math.min(value.length, offset + limit)
    // Avoid cutting a surrogate pair in the middle.
    if (end < value.length && end > offset && /[\uD800-\uDBFF]/.test(value[end - 1])) end -= 1
    const final = end === value.length
    parts.push({ ...line, text: value.slice(offset, end),
      kind: offset === 0 ? line.kind : 'default',
      isJsonMessage: final && line.isJsonMessage,
      jsonText: final ? line.jsonText : '',
      __terminalContinuation: offset > 0,
    })
    offset = end
  }
  return parts
}
export function trimTerminalWindow(lines, direction = 'older', limits = TERMINAL_HISTORY) {
  const result = Array.isArray(lines) ? lines.slice() : []
  let bytes = result.reduce((sum, item) => sum + terminalLineBytes(item), 0)
  while (result.length > 1 && (result.length > limits.visibleLines || bytes > limits.visibleBytes)) {
    const removed = direction === 'older' ? result.pop() : result.shift()
    bytes -= terminalLineBytes(removed)
  }
  return result
}

// The store owns history, never the Vue render array. Writes per client are ordered,
// and a clear fences queued writes so a delayed flush cannot resurrect old rows.
export class TerminalHistoryStore {
  constructor({ scope, indexedDBFactory = globalThis.indexedDB, onError = () => {} } = {}) {
    this.scope = String(scope || '')
    this.factory = indexedDBFactory
    this.onError = onError
    this.dbPromise = null
    this.clients = new Map()
  }
  async database() {
    if (!this.factory) throw new Error('IndexedDB is unavailable')
    if (!this.dbPromise) this.dbPromise = openDatabase(this.factory).catch(error => { this.dbPromise = null; throw error })
    return this.dbPromise
  }
  state(client) {
    const id = String(client)
    if (!this.clients.has(id)) this.clients.set(id, {
      ready: null, initialized: false, nextSeq: 0, nextChunk: 0,
      pending: [], pendingOriginal: [], pendingBytes: 0, writeChain: Promise.resolve(), flushTimer: null,
      generation: 0, failed: null, hot: [], hotBytes: 0,
    })
    return this.clients.get(id)
  }
  async ensureClient(client) {
    const id = String(client)
    const state = this.state(id)
    if (state.initialized) return state
    if (!state.ready) {
      const generation = state.generation
      state.ready = (async () => {
        const db = await this.database()
        const tx = db.transaction('meta', 'readonly')
        const saved = await requestResult(tx.objectStore('meta').get([this.scope, id]))
        // Clear may run while the first metadata read is still in flight.
        if (state.generation === generation) {
          state.nextSeq = Math.max(0, saved?.nextSeq || 0)
          state.nextChunk = Math.max(0, saved?.nextChunk || 0)
        }
        for (const line of state.pending) line.__terminalSeq = state.nextSeq++
        for (const pair of state.pendingOriginal) pair.source.__terminalSeq = pair.snapshot.__terminalSeq
        state.pendingOriginal = []
        state.initialized = true
        if (state.pending.length) this.scheduleFlush(id)
        return state
      })().catch(error => { state.ready = null; throw error })
    }
    return state.ready
  }
  append(client, lines) {
    const id = String(client)
    const state = this.state(id)
    const batch = Array.isArray(lines) ? lines : []
    for (const line of batch) {
      if (state.initialized) line.__terminalSeq = state.nextSeq++
      // Incoming operation metadata can contain Vue proxies; IndexedDB only accepts
      // structured-cloneable values. Keep the persisted snapshot independent.
      const snapshot = JSON.parse(JSON.stringify(line))
      if (!state.initialized) state.pendingOriginal.push({ source: line, snapshot })
      state.pending.push(snapshot)
      state.pendingBytes += terminalLineBytes(snapshot)
      state.hot.push(snapshot)
      state.hotBytes += terminalLineBytes(snapshot)
      while (state.hot.length > 1 &&
        (state.hot.length > TERMINAL_HISTORY.cacheLines || state.hotBytes > TERMINAL_HISTORY.cacheBytes)) {
        state.hotBytes -= terminalLineBytes(state.hot.shift())
      }
    }
    if (state.initialized && !state.failed) this.scheduleFlush(id)
    else if (!state.ready && !state.failed) void this.ensureClient(id).catch(error => this.fail(id, error))
    return batch
  }
  scheduleFlush(client) {
    const state = this.state(client)
    if (state.flushTimer !== null || state.failed) return
    state.flushTimer = setTimeout(() => {
      state.flushTimer = null
      void this.flush(client).catch(error => this.fail(client, error))
    }, state.pendingBytes >= TERMINAL_HISTORY.chunkBytes ? 0 : TERMINAL_HISTORY.flushDelayMs)
  }
  fail(client, error) {
    const state = this.state(client)
    if (!state.failed) {
      state.failed = error
      this.onError(error)
    }
  }
  async flush(client) {
    const id = String(client)
    const state = await this.ensureClient(id)
    if (state.flushTimer !== null) { clearTimeout(state.flushTimer); state.flushTimer = null }
    if (state.failed) throw state.failed
    if (!state.pending.length) { await state.writeChain; return }
    const pending = state.pending.splice(0)
    state.pendingBytes = 0
    const generation = state.generation
    const job = async () => {
      if (generation !== state.generation) return
      const db = await this.database()
      const chunks = []
      let part = [], size = 0
      for (const line of pending) {
        const lineSize = terminalLineBytes(line)
        if (part.length && size + lineSize > TERMINAL_HISTORY.chunkBytes) {
          chunks.push(part); part = []; size = 0
        }
        part.push(line); size += lineSize
      }
      if (part.length) chunks.push(part)
      const tx = db.transaction(['chunks', 'meta'], 'readwrite')
      const store = tx.objectStore('chunks')
      for (const items of chunks) {
        store.put({ scope: this.scope, client: id, chunk: state.nextChunk++,
          from: items[0].__terminalSeq, to: items[items.length - 1].__terminalSeq, items })
      }
      tx.objectStore('meta').put({ scope: this.scope, client: id,
        nextSeq: state.nextSeq, nextChunk: state.nextChunk })
      await transactionDone(tx)
    }
    const queued = state.writeChain.catch(() => {}).then(job)
    state.writeChain = queued.catch(error => {
      // Keep failed writes in RAM for full export; never silently discard data.
      if (generation === state.generation) {
        state.pending.unshift(...pending)
        state.pendingBytes += pending.reduce((sum, line) => sum + terminalLineBytes(line), 0)
        this.fail(id, error)
      }
    })
    await state.writeChain
    if (state.failed) throw state.failed
  }
  // Chunks are append-only, ordered by monotonically increasing terminal sequence.
  // Seek via the existing chunk primary key instead of traversing all chunks from
  // the end (or beginning) on every page. No IndexedDB schema change is needed.
  async findReadChunk(db, id, count, { before, after, reverse }) {
    if (!count) return null
    if (reverse && before === Infinity) return count - 1
    if (!reverse && after < 0) return 0
    let low = 0, high = count
    while (low < high) {
      const mid = Math.floor((low + high) / 2)
      const tx = db.transaction('chunks', 'readonly')
      const item = await requestResult(tx.objectStore('chunks').get([this.scope, id, mid]))
      if (!item) throw new Error(`Terminal history chunk ${mid} is missing`)
      if (reverse ? item.from < before : item.to <= after) low = mid + 1
      else high = mid
    }
    // Reverse: find the last chunk whose first row is earlier than cursor.
    // Forward: find the first chunk whose last row is newer than cursor.
    return reverse ? (low ? low - 1 : null) : (low < count ? low : null)
  }

  async read(client, { before = Infinity, after = -1, lines = Infinity, bytes = Infinity, reverse = false } = {}) {
    const id = String(client)
    const state = await this.ensureClient(id)
    if (!state.failed) await this.flush(id)
    const db = await this.database()
    const startChunk = await this.findReadChunk(db, id, state.nextChunk, { before, after, reverse })
    const result = []
    let size = 0
    if (startChunk !== null) {
      const tx = db.transaction('chunks', 'readonly')
      const keyRange = reverse
        ? IDBKeyRange.bound([this.scope, id, 0], [this.scope, id, startChunk])
        : IDBKeyRange.bound([this.scope, id, startChunk], [this.scope, id, MAX_CHUNK])
      await new Promise((resolve, reject) => {
        const cursorRequest = tx.objectStore('chunks').openCursor(keyRange, reverse ? 'prev' : 'next')
        cursorRequest.onerror = () => reject(cursorRequest.error)
        cursorRequest.onsuccess = () => {
          const cursor = cursorRequest.result
          if (!cursor) { resolve(); return }
          const items = reverse ? cursor.value.items.slice().reverse() : cursor.value.items
          for (const item of items) {
            if (item.__terminalSeq >= before || item.__terminalSeq <= after) continue
            const itemSize = terminalLineBytes(item)
            if (result.length && (result.length >= lines || size + itemSize > bytes)) { resolve(); return }
            result.push(item); size += itemSize
          }
          cursor.continue()
        }
      })
    }
    const pending = state.pending.filter(line => line.__terminalSeq !== undefined &&
      line.__terminalSeq < before && line.__terminalSeq > after)
    if (state.failed) {
      const combined = reverse ? [...pending.reverse(), ...result] : [...result, ...pending]
      return combined
    }
    return reverse ? result.reverse() : result
  }
  async readBefore(client, before = Infinity, lines = TERMINAL_HISTORY.loadLines, bytes = TERMINAL_HISTORY.loadBytes) {
    const state = await this.ensureClient(client)
    // Recent history can be served from a small bounded RAM cache without an
    // IndexedDB roundtrip during normal scrolling or auto-follow.
    if (!state.failed) {
      const candidates = state.hot.filter(item => item.__terminalSeq < before).reverse()
      let size = 0
      let reachedLimit = false
      const recent = []
      for (const item of candidates) {
        const itemSize = terminalLineBytes(item)
        if (recent.length && (recent.length >= lines || size + itemSize > bytes)) {
          reachedLimit = true
          break
        }
        recent.push(item); size += itemSize
      }
      if (recent.length && (reachedLimit || size >= bytes)) return recent.reverse()
    }
    return this.read(client, { before, lines, bytes, reverse: true })
  }
  readAfter(client, after = -1, lines = TERMINAL_HISTORY.loadLines, bytes = TERMINAL_HISTORY.loadBytes) {
    return this.read(client, { after, lines, bytes })
  }
  readAll(client) { return this.read(client) }
  clear(client) {
    const id = String(client)
    const state = this.state(id)
    const ready = this.ensureClient(id)
    // Fence immediately, before any await. Rows appended after Clear belong to
    // the new generation even if an older disk write is still in flight.
    state.generation += 1
    state.nextSeq = 0
    state.pending = []
    state.pendingOriginal = []
    state.pendingBytes = 0
    state.hot = []
    state.hotBytes = 0
    state.failed = null
    if (state.flushTimer !== null) { clearTimeout(state.flushTimer); state.flushTimer = null }
    const job = async () => {
      await ready
      const db = await this.database()
      const tx = db.transaction(['chunks', 'meta'], 'readwrite')
      const range = IDBKeyRange.bound([this.scope, id, 0], [this.scope, id, MAX_CHUNK])
      tx.objectStore('chunks').delete(range)
      state.nextChunk = 0
      tx.objectStore('meta').put({ scope: this.scope, client: id, nextSeq: 0, nextChunk: 0 })
      await transactionDone(tx)
    }
    state.writeChain = state.writeChain.catch(() => {}).then(job)
    return state.writeChain.then(() => {
      if (state.pending.length) this.scheduleFlush(id)
    })
  }
  async clearScope() {
    const db = await this.database()
    await Promise.all([...this.clients.keys()].map(id => this.flush(id).catch(() => {})))
    const tx = db.transaction(['chunks', 'meta'], 'readwrite')
    for (const table of ['chunks', 'meta']) {
      const object = tx.objectStore(table)
      const cursor = object.openCursor()
      cursor.onsuccess = () => {
        if (!cursor.result) return
        if (cursor.result.value.scope === this.scope) cursor.result.delete()
        cursor.result.continue()
      }
    }
    await transactionDone(tx)
    this.clients.clear()
  }
}
