import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { webcrypto } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { test } from 'node:test'

const html = readFileSync(new URL('../public/login.html', import.meta.url), 'utf8')
const inline = html.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(inline)

function harness(password = 'sensitive-secret-密码') {
  const messages = []
  const elements = {
    username: { value: 'admin', focus() {} }, password: { value: password, focus() {} },
    submitButton: { disabled: false, textContent: 'Sign In' }, loginForm: { addEventListener() {} },
  }
  let loginResponse = { ok: false, status: 401 }
  const calls = []
  let failNetwork = false
  const context = {
    crypto: webcrypto, TextEncoder, Uint8Array, URLSearchParams, btoa,
    window: { location: { search: '', replace() {} }, isSecureContext: false, setTimeout() {} },
    document: { getElementById: id => elements[id] },
    ElementPlus: {
      ElLoading: { service: () => ({ close() {} }) },
      ElMessage: Object.assign(options => messages.push(options.message), { closeAll() {} }),
    },
    fetch: async (url, options) => {
      calls.push({ url, options })
      if (url.endsWith('/session')) return { ok: true, json: async () => ({ data: { authenticated: false } }) }
      if (failNetwork) throw new TypeError('Failed to fetch')
      return loginResponse
    },
  }
  vm.runInNewContext(inline + '\nthis.testMask = maskedLoginPayload; this.testLogin = handleLogin;', context)
  return {
    context, calls, elements, messages,
    setLoginResponse: response => { loginResponse = response },
    failNetwork: () => { failNetwork = true },
  }
}

function unmask(payload) {
  const key = Buffer.from('RCH-login-transport-mask')
  const nonce = Buffer.from(payload.mask_nonce, 'base64')
  return Buffer.from(payload.masked_password, 'base64').map((value, index) =>
    value ^ key[index % key.length] ^ nonce[index % nonce.length]
  ).toString('utf8')
}

test('login hides raw password in a one-request reversible mask', () => {
  const h = harness()
  const body = h.context.testMask('admin', 'sensitive-secret-密码')
  assert.ok(!('password' in body))
  assert.ok(!JSON.stringify(body).includes('sensitive-secret'))
  assert.equal(unmask(body), 'sensitive-secret-密码')
  const second = h.context.testMask('admin', 'sensitive-secret-密码')
  assert.notEqual(body.masked_password, second.masked_password)
})

test('masked payload produced by the browser decodes correctly in the real Python helper', () => {
  const body = harness().context.testMask('admin', 'unicode-密码-🧭')
  const command = [
    'import json, sys',
    'from server.web.password_mask import decode_masked_password',
    'print(decode_masked_password(json.loads(sys.stdin.read())))',
  ].join('; ')
  const out = spawnSync('python', ['-c', command], {
    cwd: new URL('../../backend/', import.meta.url).pathname,
    encoding: 'utf8', input: JSON.stringify(body),
  })
  assert.equal(out.status, 0, out.stderr)
  assert.equal(out.stdout.trim(), 'unicode-密码-🧭')
})

test('ordinary HTTP context is allowed, and login errors remain distinct', async () => {
  const rejected = harness()
  await rejected.context.testLogin({ preventDefault() {} })
  assert.equal(rejected.messages.at(-1), 'Invalid username or password')
  assert.equal(rejected.calls.filter(({ url }) => url.endsWith('/login')).length, 1)
  assert.ok(!JSON.stringify(rejected.calls.at(-1).options).includes('sensitive-secret'))
  assert.equal(rejected.elements.password.value, '')
  const offline = harness()
  offline.failNetwork()
  await offline.context.testLogin({ preventDefault() {} })
  assert.match(offline.messages.at(-1), /Network error/)
  const serverError = harness()
  serverError.setLoginResponse({ ok: false, status: 503 })
  await serverError.context.testLogin({ preventDefault() {} })
  assert.equal(serverError.messages.at(-1), 'Server error. Please try again.')
})

test('no HTTPS requirement or unused challenge endpoint remains', () => {
  assert.doesNotMatch(inline, /isSecureContext|crypto\.subtle|LOGIN_CHALLENGE_URL|login-challenge|HTTPS or localhost/)
})
