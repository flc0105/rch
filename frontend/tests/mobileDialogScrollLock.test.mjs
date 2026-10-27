import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { installMobileDialogScrollLock } from '../src/utils/mobileDialogScrollLock.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

class FakeStyle {
  constructor(values = {}) {
    this.values = { ...values }
    this.display = values.display || ''
  }
  getPropertyValue(property) { return this.values[property] || '' }
  getPropertyPriority(property) { return '' }
  setProperty(property, value) { this.values[property] = String(value) }
  removeProperty(property) { delete this.values[property] }
}

class FakeClassList {
  constructor() { this.values = new Set() }
  add(value) { this.values.add(value) }
  remove(value) { this.values.delete(value) }
  contains(value) { return this.values.has(value) }
}

class FakeObserver {
  static instances = []
  constructor(callback) { this.callback = callback; FakeObserver.instances.push(this) }
  observe() {}
  disconnect() { this.disconnected = true }
  trigger(records = []) { this.callback(records) }
}

function makeEnvironment({ mobile = true, windowScrollY = 42, appScrollTop = 136 } = {}) {
  FakeObserver.instances = []
  const body = { style: new FakeStyle({ color: 'red' }), classList: new FakeClassList() }
  const app = { style: new FakeStyle({ 'overflow-y': 'auto' }), scrollTop: appScrollTop }
  const overlays = []
  const documentListeners = new Map()
  const windowListeners = new Map()
  const scrollCalls = []
  const mediaListeners = new Set()
  const media = {
    matches: mobile,
    addEventListener(_name, fn) { mediaListeners.add(fn) },
    removeEventListener(_name, fn) { mediaListeners.delete(fn) },
    change(value) { this.matches = value; for (const fn of mediaListeners) fn() },
  }
  const windowRef = {
    innerWidth: mobile ? 390 : 1280,
    scrollY: windowScrollY,
    pageYOffset: windowScrollY,
    matchMedia: () => media,
    getComputedStyle: element => ({
      display: element.style?.display === 'none' ? 'none' : 'block',
      visibility: 'visible',
    }),
    scrollTo: (x, y) => scrollCalls.push([x, y]),
    addEventListener: (name, fn) => windowListeners.set(name, fn),
    removeEventListener: name => windowListeners.delete(name),
  }
  const documentRef = {
    body,
    getElementById: id => id === 'app' ? app : null,
    querySelectorAll: selector => selector === '.el-overlay' ? overlays : [],
    addEventListener: (name, fn) => documentListeners.set(name, fn),
    removeEventListener: name => documentListeners.delete(name),
  }
  const addDialog = (kind = 'el-dialog') => {
    const dialog = { style: new FakeStyle() }
    const overlay = {
      style: new FakeStyle(),
      getAttribute: () => null,
      matches: selector => selector.includes('.el-overlay'),
      closest: selector => selector.includes('.el-overlay') ? overlay : null,
      querySelector: selector => selector.split(',').map(value => value.trim()).includes(`.${kind}`) ? dialog : null,
      dialog,
    }
    overlays.push(overlay)
    return overlay
  }
  return { body, app, overlays, documentListeners, windowListeners, scrollCalls, media, addDialog, documentRef, windowRef }
}

const observer = () => FakeObserver.instances.at(-1)

test('mobile dialog locks the body and app scroller, then restores both scroll positions and inline styles', () => {
  const env = makeEnvironment()
  const stop = installMobileDialogScrollLock({
    documentRef: env.documentRef,
    windowRef: env.windowRef,
    MutationObserverClass: FakeObserver,
  })
  const overlay = env.addDialog()
  observer().trigger([{ type: 'childList', target: env.body }])

  assert.equal(env.body.classList.contains('rch-mobile-dialog-open'), true)
  assert.equal(env.body.style.getPropertyValue('position'), 'fixed')
  assert.equal(env.body.style.getPropertyValue('top'), '-42px')
  assert.equal(env.app.style.getPropertyValue('overflow-y'), 'hidden')

  let prevented = false
  env.documentListeners.get('touchmove')({ target: { closest: () => null }, preventDefault() { prevented = true } })
  assert.equal(prevented, true, 'touch moves outside dialogs are prevented')
  prevented = false
  env.documentListeners.get('touchmove')({ target: { closest: selector => selector.includes('.el-dialog') ? {} : null }, preventDefault() { prevented = true } })
  assert.equal(prevented, false, 'touch moves inside dialogs remain available for internal scrolling')

  overlay.style.display = 'none'
  observer().trigger([{ type: 'attributes', target: overlay }])
  assert.equal(env.body.classList.contains('rch-mobile-dialog-open'), false)
  assert.equal(env.body.style.getPropertyValue('position'), '')
  assert.equal(env.body.style.getPropertyValue('color'), 'red')
  assert.equal(env.app.style.getPropertyValue('overflow-y'), 'auto')
  assert.equal(env.app.scrollTop, 136)
  assert.deepEqual(env.scrollCalls.at(-1), [0, 42])
  stop()
})

test('nested dialogs keep the page locked until the last visible dialog closes', () => {
  const env = makeEnvironment()
  const stop = installMobileDialogScrollLock({
    documentRef: env.documentRef,
    windowRef: env.windowRef,
    MutationObserverClass: FakeObserver,
  })
  const first = env.addDialog()
  const second = env.addDialog()
  observer().trigger([{ type: 'childList', target: env.body }])
  first.style.display = 'none'
  observer().trigger([{ type: 'attributes', target: first }])
  assert.equal(env.body.classList.contains('rch-mobile-dialog-open'), true)
  second.style.display = 'none'
  observer().trigger([{ type: 'attributes', target: second }])
  assert.equal(env.body.classList.contains('rch-mobile-dialog-open'), false)
  stop()
})

test('mobile Element Plus message boxes also lock page scrolling', () => {
  const env = makeEnvironment()
  const stop = installMobileDialogScrollLock({
    documentRef: env.documentRef,
    windowRef: env.windowRef,
    MutationObserverClass: FakeObserver,
  })
  const overlay = env.addDialog('el-message-box')
  observer().trigger([{ type: 'childList', target: env.body }])
  assert.equal(env.body.classList.contains('rch-mobile-dialog-open'), true)
  overlay.style.display = 'none'
  observer().trigger([{ type: 'attributes', target: overlay }])
  assert.equal(env.body.classList.contains('rch-mobile-dialog-open'), false)
  stop()
})

test('desktop dialogs do not activate the mobile scroll lock and a viewport change unlocks it', () => {
  const env = makeEnvironment({ mobile: false })
  const stop = installMobileDialogScrollLock({
    documentRef: env.documentRef,
    windowRef: env.windowRef,
    MutationObserverClass: FakeObserver,
  })
  env.addDialog()
  observer().trigger([{ type: 'childList', target: env.body }])
  assert.equal(env.body.classList.contains('rch-mobile-dialog-open'), false)

  env.media.change(true)
  assert.equal(env.body.classList.contains('rch-mobile-dialog-open'), true)
  env.media.change(false)
  assert.equal(env.body.classList.contains('rch-mobile-dialog-open'), false)
  stop()
})

test('Main entry installs the global lock and CSS confines scroll chaining to dialog content', () => {
  const main = read('../src/main.js')
  const css = read('../src/styles/mobileDialogs.css')
  assert.match(main, /installMobileDialogScrollLock\(\)/)
  assert.match(main, /app\.onUnmount\(stopMobileDialogScrollLock\)/)
  assert.match(css, /body\.rch-mobile-dialog-open #app\s*\{[^}]*overflow-y:\s*hidden/s)
  assert.match(css, /overscroll-behavior:\s*contain/)
  assert.match(read('../src/utils/mobileDialogScrollLock.js'), /querySelector\('\.el-dialog, \.el-message-box'\)/)
})
