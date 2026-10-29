import assert from 'node:assert/strict'
import { test } from 'node:test'
import { scheduleIdleWarmup } from '../src/utils/idleWarmup.js'

test('idle warmup waits for initial load and two frames, then imports sequentially', async () => {
  const oldWindow = globalThis.window
  const oldDocument = globalThis.document
  const listeners = new Map()
  const frames = []
  const idles = []
  const loaded = []
  globalThis.document = { readyState: 'loading', hidden: false, addEventListener: (n, f) => listeners.set(n, f), removeEventListener: n => listeners.delete(n) }
  globalThis.window = {
    addEventListener: (n, f) => listeners.set(n, f), removeEventListener: n => listeners.delete(n),
    requestAnimationFrame: f => { frames.push(f); return frames.length }, cancelAnimationFrame() {},
    requestIdleCallback: f => { idles.push(f); return idles.length }, cancelIdleCallback() {},
  }
  try {
    const stop = scheduleIdleWarmup([() => loaded.push('preview'), () => loaded.push('pty')])
    assert.deepEqual(loaded, [])
    assert.equal(frames.length, 0)
    listeners.get('load')()
    assert.equal(frames.length, 1)
    frames.shift()()
    frames.shift()()
    assert.equal(idles.length, 1)
    idles.shift()()
    await new Promise(resolve => setImmediate(resolve))
    assert.deepEqual(loaded, ['preview'])
    assert.equal(idles.length, 1)
    idles.shift()()
    await new Promise(resolve => setImmediate(resolve))
    assert.deepEqual(loaded, ['preview', 'pty'])
    stop()
  } finally { globalThis.window = oldWindow; globalThis.document = oldDocument }
})

test('idle warmup can cancel pending tasks', () => {
  const oldWindow = globalThis.window
  const oldDocument = globalThis.document
  let callback
  let canceled = false
  globalThis.document = { readyState: 'complete', hidden: false, addEventListener() {}, removeEventListener() {} }
  globalThis.window = {
    requestAnimationFrame: f => { callback = f; return 1 }, cancelAnimationFrame: () => { canceled = true },
  }
  try {
    const stop = scheduleIdleWarmup([() => { throw new Error('should not run') }])
    assert.equal(typeof callback, 'function')
    stop()
    assert.equal(canceled, true)
  } finally { globalThis.window = oldWindow; globalThis.document = oldDocument }
})

test('lazy dialog wiring is preserved with complete Element Plus UI styles', async () => {
  const { readFileSync } = await import('node:fs')
  const { fileURLToPath } = await import('node:url')
  const { dirname, resolve } = await import('node:path')
  const src = resolve(dirname(fileURLToPath(import.meta.url)), '../src')
  const app = readFileSync(resolve(src, 'App.vue'), 'utf8')
  const main = readFileSync(resolve(src, 'main.js'), 'utf8')
  for (const name of ['preview', 'documents', 'pty', 'processes', 'keychains']) {
    assert.match(app, new RegExp(`dialogComponents\\.${name}`))
  }
  for (const name of [
    'openExternalToolMetaEditor', 'previewRemoteEntry', 'previewArtifact',
    'previewBackgroundJobFile', 'openNewRemoteScriptEditor',
    'openRemoteScriptEditorInternal', 'openNewRemoteJobEditor',
    'openNewSharedFileEditor', 'openRemoteJobEditor',
  ]) assert.match(app, new RegExp(`this\\.callOptionalDialog\\('preview', '${name}'`))
  assert.match(main, /\.use\(ElementPlus\)/)
  assert.match(main, /element-plus\/dist\/index\.css/)
  assert.doesNotMatch(main, /window\.ElementPlus/)
})

test('full Element Plus CSS and plugin restore the original UI styling', async () => {
  const { readFileSync } = await import('node:fs')
  const { fileURLToPath } = await import('node:url')
  const { dirname, resolve } = await import('node:path')
  const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
  const main = readFileSync(resolve(frontend, 'src/main.js'), 'utf8')
  const vite = readFileSync(resolve(frontend, 'vite.config.js'), 'utf8')
  const pkg = JSON.parse(readFileSync(resolve(frontend, 'package.json'), 'utf8'))
  const lock = JSON.parse(readFileSync(resolve(frontend, 'package-lock.json'), 'utf8'))
  assert.match(main, /import ElementPlus from ['"]element-plus['"]/) 
  assert.match(main, /import ['"]element-plus\/dist\/index\.css['"]/) 
  assert.match(main, /createApp\(Root\)\.use\(ElementPlus\)/)
  assert.doesNotMatch(main, /registerElementPlusComponents|elementPlusRegistry/)
  assert.doesNotMatch(main, /element-plus\/es\/components\/.*\/style\/css/)
  assert.doesNotMatch(vite, /unplugin-vue-components|ElementPlusResolver/)
  assert.equal(pkg.devDependencies['unplugin-vue-components'], undefined)
  assert.deepEqual(pkg.devDependencies, lock.packages[''].devDependencies)
})

test('optional dialog idle queue follows user priority and keeps hover/click/notification routes', async () => {
  const { readFileSync } = await import('node:fs')
  const { fileURLToPath } = await import('node:url')
  const { dirname, resolve } = await import('node:path')
  const src = resolve(dirname(fileURLToPath(import.meta.url)), '../src')
  const app = readFileSync(resolve(src, 'App.vue'), 'utf8')
  const priorities = ['externalTools', 'commandHistory', 'pty', 'backgroundJobs', 'processes', 'keychains', 'preview', 'documents']
  const mounted = app.slice(app.indexOf('  async mounted() {'), app.indexOf('  beforeUnmount() {'))
  const tasks = [...mounted.matchAll(/\(\) => loadOptionalDialog\('([^']+)'\)/g)].map(match => match[1])
  assert.deepEqual(tasks, priorities)
  for (const [name, file] of [
    ['externalTools', 'ExternalToolManagerDialog'],
    ['commandHistory', 'CommandHistoryDialog'],
    ['backgroundJobs', 'BackgroundJobsDialog'],
  ]) {
    assert.ok(app.includes(`${name}: () => import('./components/${file}.vue')`))
    assert.match(app, new RegExp(`:is="dialogComponents\\.${name}"`))
    assert.match(app, new RegExp(`v-if="dialogComponents\\.${name}"`))
    assert.doesNotMatch(app, new RegExp(`import ${file} from`))
  }
  for (const [action, name] of [
    ['external-tools', 'externalTools'], ['history', 'commandHistory'], ['jobs', 'backgroundJobs'],
  ]) assert.ok(app.includes(`'${action}': '${name}'`) || app.includes(`${action}: '${name}'`))
  assert.match(app, /this\.callOptionalDialog\('externalTools', 'openFromNotification', context, \{ viewLog: true \}\)/)
  assert.match(app, /this\.callOptionalDialog\('externalTools', 'openFromNotification', context\)/)
  for (const [method, name] of [
    ['openExternalToolManagerDialog', 'externalTools'],
    ['openBackgroundJobsDialog', 'backgroundJobs'],
    ['openCommandHistoryDialog', 'commandHistory'],
  ]) {
    const body = app.slice(app.indexOf(`    ${method}()`), app.indexOf('\n    },', app.indexOf(`    ${method}()`)))
    assert.ok(body.includes(`this.callOptionalDialog('${name}', 'open')`))
  }
  assert.match(app, /await this\.\$nextTick\(\)\n      return this\.\$refs\[optionalDialogRefs\[name\]\]/)
  assert.match(app, /name === 'externalTools' && method === 'open' && dialog\?\.isOpen\?\.\(\)/)
  assert.match(app, /refreshBackgroundJobsIfOpen\(\)\s*\{\s*return this\.\$refs\.backgroundJobsDialogRef\?\.refreshIfOpen\(\)/)
})
