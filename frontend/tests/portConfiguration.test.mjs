import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const src = readFileSync(new URL('../src/api/streamApi.js', import.meta.url), 'utf8')
const pty = readFileSync(new URL('../src/components/PtyDialog.vue', import.meta.url), 'utf8')
const screen = readFileSync(new URL('../src/components/ScreenViewDialog.vue', import.meta.url), 'utf8')
const vite = readFileSync(new URL('../vite.config.js', import.meta.url), 'utf8')

function buildUrlHelper(dev, href) {
  const helper = src.match(/export function webSocketUrl\(path\) \{[\s\S]*?\n\}/)?.[0]
  assert.ok(helper, 'webSocketUrl is exported')
  const code = helper.replace('export ', '').replace('import.meta.env?.DEV', String(dev))
  const url = new URL(href)
  return new Function('window', `${code}\nreturn webSocketUrl`)( { location: url } )
}

test('production events, PTY and Screen route to the HTTP port + 1 without fixed ports', () => {
  const production = buildUrlHelper(false, 'http://example.test:9090/console')
  assert.equal(production('/ws/events?tab_id=a'), 'ws://example.test:9091/ws/events?tab_id=a')
  assert.equal(buildUrlHelper(false, 'http://example.test:8085/')('/ws/pty/abc'), 'ws://example.test:8086/ws/pty/abc')
  assert.equal(buildUrlHelper(false, 'https://example.test:8443/')('/ws/screen/abc'), 'wss://example.test:8444/ws/screen/abc')
  for (const component of [pty, screen]) {
    assert.match(component, /import \{ webSocketUrl \} from '\.\.\/api\/streamApi\.js'/)
    assert.match(component, /webSocketUrl\(/)
    assert.doesNotMatch(component, /url\.port\s*=|location\.port === '5173'/)
  }
})

test('development routes all websocket subscriptions through Vite proxy on arbitrary dev port', () => {
  assert.equal(buildUrlHelper(true, 'http://127.0.0.1:5173/')('/ws/events'), 'ws://127.0.0.1:5173/ws/events')
  assert.equal(buildUrlHelper(true, 'http://127.0.0.1:5300/')('/ws/events'), 'ws://127.0.0.1:5300/ws/events')
  assert.equal(buildUrlHelper(true, 'https://example.test:5300/')('/ws/events'), 'wss://example.test:5300/ws/events')
})

test('Vite proxies use server configurable port instead of literals', () => {
  assert.match(vite, /process\.env\.RCH_WEB_PORT/)
  assert.match(vite, /process\.env\.RCH_VITE_PORT/)
  assert.match(vite, /target:\s*`http:\/\/127\.0\.0\.1:\$\{webPort\}`/)
  assert.match(vite, /target:\s*`ws:\/\/127\.0\.0\.1:\$\{webPort \+ 1\}`/)
  assert.match(vite, /target:\s*`ws:\/\/127\.0\.0\.1:\$\{webPort \+ 1\}`,[\s\S]*?changeOrigin: false/)
})
