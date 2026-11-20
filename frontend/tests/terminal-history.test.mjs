import assert from 'node:assert/strict'
import { test } from 'node:test'
import { TerminalHistoryStore } from '../src/utils/terminalHistoryStore.js'

// Small asynchronous IndexedDB test double; no browser or npm test dependencies.
function fakeIndexedDB(t) {
  const data = new Map()
  const keys = new Set()
  const compare = (a, b) => { const left = JSON.stringify(a), right = JSON.stringify(b); return left < right ? -1 : left > right ? 1 : 0 }
  const previousRange = Object.getOwnPropertyDescriptor(globalThis, 'IDBKeyRange')
  globalThis.IDBKeyRange = { bound: (lower, upper) => ({ lower, upper }) }
  t.after(() => {
    if (previousRange) Object.defineProperty(globalThis, 'IDBKeyRange', previousRange)
    else delete globalThis.IDBKeyRange
  })
  function request(callback) {
    const r = { result: undefined, error: null }
    queueMicrotask(() => {
      try { r.result = callback(); r.onsuccess?.() }
      catch (error) { r.error = error; r.onerror?.() }
    })
    return r
  }
  function objectStore(name) {
    if (!data.has(name)) data.set(name, new Map())
    const records = data.get(name)
    const key = item => JSON.stringify(name === 'chunks' ? [item.scope, item.client, item.chunk] : [item.scope, item.client])
    return {
      get: parts => request(() => records.get(JSON.stringify(parts))),
      put: value => { records.set(key(value), structuredClone(value)); return request(() => undefined) },
      delete: range => request(() => {
        for (const [k, v] of records) {
          const parts = JSON.parse(k)
          if (compare(parts, range.lower) >= 0 && compare(parts, range.upper) <= 0) records.delete(k)
        }
      }),
      openCursor: (range, direction) => {
        const rows = [...records.values()].filter(value => {
          const k = JSON.parse(key(value))
          return !range || compare(k, range.lower) >= 0 && compare(k, range.upper) <= 0
        }).sort((a,b)=> compare(JSON.parse(key(a)), JSON.parse(key(b))))
        if (direction === 'prev') rows.reverse()
        let index = 0
        const r = {}
        const next = () => queueMicrotask(() => {
          r.result = index < rows.length ? {
            value: structuredClone(rows[index]),
            delete() { records.delete(key(rows[index])) },
            continue() { index++; next() },
          } : null
          r.onsuccess?.()
        })
        next()
        return r
      },
    }
  }
  const db = {
    objectStoreNames: { contains: name => keys.has(name) },
    createObjectStore: name => { keys.add(name); objectStore(name) },
    transaction() {
      const tx = { objectStore }
      setTimeout(() => tx.oncomplete?.(), 0)
      return tx
    },
  }
  return { open() {
    const r = { result: db }
    queueMicrotask(() => { r.onupgradeneeded?.(); r.onsuccess?.() })
    return r
  } }
}
const line = (i, extra = {}) => ({ text: `line-${i}`, kind: 'default', meta: extra })

test('IndexedDB writes complete ordered output in chunks, and pages in both directions', async (t) => {
  const factory = fakeIndexedDB(t)
  const history = new TerminalHistoryStore({ scope: 'alice:tab1', indexedDBFactory: factory })
  const original = Array.from({ length: 1000 }, (_, i) => line(i, { operation_id: i < 50 ? 'op-a' : 'op-b' }))
  history.append('client-a', original)
  await history.flush('client-a')
  const tail = await history.readBefore('client-a', Infinity, 200, Infinity)
  assert.deepEqual(tail.map(item => item.text), original.slice(-200).map(item => item.text))
  assert.equal(tail[0].__terminalSeq, 800)
  const earlier = await history.readBefore('client-a', tail[0].__terminalSeq, 200, Infinity)
  assert.equal(earlier[0].text, 'line-600')
  const later = await history.readAfter('client-a', earlier.at(-1).__terminalSeq, 200, Infinity)
  assert.equal(later[0].text, 'line-800')
  const reopened = new TerminalHistoryStore({ scope: 'alice:tab1', indexedDBFactory: factory })
  assert.equal((await reopened.readAll('client-a')).length, 1000)
  assert.equal((await reopened.readAll('client-b')).length, 0)
  const otherTab = new TerminalHistoryStore({ scope: 'alice:tab2', indexedDBFactory: factory })
  assert.equal((await otherTab.readAll('client-a')).length, 0)
})

test('Clear fences pending writes and removes history permanently, retaining post-Clear output', async (t) => {
  const factory = fakeIndexedDB(t)
  const history = new TerminalHistoryStore({ scope: 'bob:tab1', indexedDBFactory: factory })
  history.append('dev', [line(1)])
  await history.flush('dev')
  history.append('dev', [line(2)])
  const clearing = history.clear('dev')
  history.append('dev', [line(3)])
  await clearing
  await history.flush('dev')
  assert.deepEqual((await history.readAll('dev')).map(item => item.text), ['line-3'])
  const reopened = new TerminalHistoryStore({ scope: 'bob:tab1', indexedDBFactory: factory })
  assert.deepEqual((await reopened.readAll('dev')).map(item => item.text), ['line-3'])
  await history.clear('dev')
  assert.equal((await reopened.readAll('dev')).length, 0)
})
