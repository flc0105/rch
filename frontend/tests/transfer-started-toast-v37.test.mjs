import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const app = read('../src/App.vue')
const source = read('../src/utils/transferStartedToast.js')
const cases = [
  ['RemoteFilesDialog.vue', ['Upload started', 'Download started']],
  ['RemoteFilePicker.vue', ['Upload started']],
  ['ClipboardDialog.vue', ['Download started', 'Preparing ZIP download']],
  ['RemoteZipEntryActions.vue', ['Download started']],
]

function renderToast() {
  const shown = []
  const failures = []
  const h = (component, props, children) => (typeof props === 'string' || Array.isArray(props))
    ? ({ component, props: null, children: props }) : ({ component, props, children })
  const ElMessage = {
    success(options) {
      const toast = { options, closed: false, close() { this.closed = true } }
      shown.push(toast)
      return toast
    },
    error(message) { failures.push(message) },
  }
  const code = source.replace(/^import .*$/gm, '')
    .replace('export const ', 'const ')
    .replace('export function ', 'function ')
  const api = vm.runInNewContext(`(() => { ${code}; return { OPEN_TRANSFER_CENTER_KEY, showTransferStartedToast } })()`,
    { h, ElMessage, Promise })
  return { ...api, shown, failures }
}

test('Toast uses a single inline text link inside Element Plus content and opens drawer', () => {
  const ui = renderToast()
  let opens = 0
  let stopped = 0
  let prevented = 0
  const toast = ui.showTransferStartedToast('Upload started: long-example-file-name.txt', () => { opens++ })
  assert.equal(ui.shown.length, 1)
  assert.equal(toast.options.duration, 5000)
  assert.equal(toast.options.customClass, 'rch-transfer-started-toast')
  const content = toast.options.message
  assert.equal(content.component, 'span')
  assert.equal(content.props.class, 'el-message__content rch-transfer-started-content')
  const label = content.children[0]
  assert.equal(label.component, 'span')
  assert.equal(label.children, 'Upload started: long-example-file-name.txt')
  assert.equal(content.children[1], ' ')
  const link = content.children[2]
  assert.equal(link.component, 'a')
  assert.equal(link.props.href, '#')
  assert.equal(link.props.title, 'Open Transfers')
  assert.equal(link.props['aria-label'], 'Open Transfers')
  assert.equal(link.children, 'Transfers')
  assert.doesNotMatch(source, /rch-transfer-started-open-short|ElLink/)
  link.props.onClick({ stopPropagation() { stopped++ }, preventDefault() { prevented++ } })
  assert.equal(opens, 1)
  assert.equal(stopped, 1)
  assert.equal(prevented, 1)
  assert.equal(toast.closed, true)
})

test('toast without injected opener keeps ordinary success presentation', () => {
  const ui = renderToast()
  const toast = ui.showTransferStartedToast('Download started: example.txt', null)
  assert.equal(toast.options, 'Download started: example.txt')
})

test('App offers a single opener to nested dialogs, including remote picker and ZIP entry', () => {
  assert.match(app, /\[OPEN_TRANSFER_CENTER_KEY\]:\s*\(\) => this\.openTransferCenter\(\)/)
  assert.match(app, /openTransferCenter\(\)\s*\{[\s\S]*?this\.\$refs\.transferCenterDrawerRef\?\.open\(\)/)
  assert.doesNotMatch(app, /openTransferCenter\(\)\s*\{\s*await this\.loadTransferItems/)
  for (const [file, messages] of cases) {
    const component = read(`../src/components/${file}`)
    assert.match(component, /inject:\s*\{ openTransferCenterFromToast:\s*\{ from: OPEN_TRANSFER_CENTER_KEY, default: null \}/)
    for (const message of messages) {
      assert.match(component, new RegExp(`showTransferStartedToast\\(\\x60${message}`))
    }
    assert.match(component, /this\.openTransferCenterFromToast/)
    if (file === 'RemoteFilesDialog.vue' || file === 'RemoteFilePicker.vue') {
      assert.match(component, /onStarted:\s*\(\)\s*=>\s*showTransferStartedToast/)
      assert.equal((component.match(/showTransferStartedToast\(`Upload started:/g) || []).length, 1)
    }
  }
  assert.doesNotMatch(read('../src/composables/useSseStream.js'), /showTransferStartedToast/)
})
