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

test('lazy dialog wiring preserves optional dialogs after Element Plus on-demand registration', async () => {
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
  assert.doesNotMatch(main, /\.use\(ElementPlus\)/)
  assert.doesNotMatch(main, /element-plus\/dist\/index\.css/)
  assert.doesNotMatch(main, /window\.ElementPlus/)
})

test('all referenced Element Plus tags and v-loading are explicitly registered', async () => {
  const { readFileSync, readdirSync } = await import('node:fs')
  const { fileURLToPath } = await import('node:url')
  const { dirname, resolve, join } = await import('node:path')
  const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
  const src = resolve(frontend, 'src')
  const registry = readFileSync(resolve(src, 'utils/elementPlusRegistry.js'), 'utf8')
  const main = readFileSync(resolve(src, 'main.js'), 'utf8')
  const vite = readFileSync(resolve(frontend, 'vite.config.js'), 'utf8')
  const pkg = JSON.parse(readFileSync(resolve(frontend, 'package.json'), 'utf8'))
  const lock = JSON.parse(readFileSync(resolve(frontend, 'package-lock.json'), 'utf8'))
  const files = []
  function walk(dir) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name)
      if (entry.isDirectory()) walk(path)
      else if (entry.name.endsWith('.vue')) files.push(path)
    }
  }
  walk(src)
  const referenced = new Set()
  let hasLoading = false
  for (const file of files) {
    const sfc = readFileSync(file, 'utf8').replace(/<!--[^]*?-->/g, '')
    for (const [, tag] of sfc.matchAll(/<(el-[a-z][\w-]*)\b/g)) referenced.add(tag)
    if (/v-loading\b/.test(sfc)) hasLoading = true
  }
  const registered = new Set([...registry.matchAll(/app\.component\('(el-[a-z][\w-]*)', (El\w+)\)/g)].map(m => m[1]))
  assert.deepEqual([...registered].sort(), [...referenced].sort())
  const parentStyle = {
    'collapse-item': 'collapse', 'descriptions-item': 'descriptions',
    'dropdown-item': 'dropdown', 'dropdown-menu': 'dropdown',
    'form-item': 'form', option: 'select', 'radio-button': 'radio',
    'radio-group': 'radio', 'tab-pane': 'tabs', 'table-column': 'table',
  }
  for (const tag of registered) {
    const suffix = tag.slice(3)
    const name = 'El' + suffix.split('-').map(part => part[0].toUpperCase() + part.slice(1)).join('')
    assert.match(registry, new RegExp(`\\b${name}\\b`))
    const style = parentStyle[suffix] || suffix
    assert.ok(registry.includes(`element-plus/es/components/${style}/style/css`))
  }
  assert.ok(hasLoading)
  assert.match(registry, /app\.directive\('loading', ElLoadingDirective\)/)
  assert.match(main, /registerElementPlusComponents\(app\)/)
  assert.doesNotMatch(vite, /unplugin-vue-components|ElementPlusResolver/)
  assert.equal(pkg.devDependencies['unplugin-vue-components'], undefined)
  assert.deepEqual(pkg.devDependencies, lock.packages[''].devDependencies)
  for (const style of ['message', 'message-box', 'notification', 'loading']) {
    assert.ok(main.includes(`element-plus/es/components/${style}/style/css`))
  }
  assert.doesNotMatch(main, /import ElementPlus from ['"]element-plus['"]|app\.use\(ElementPlus\)/)
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
