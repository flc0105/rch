import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('Documents is a server-only toolbar action', () => {
  const catalog = read('../src/data/toolbarPreferences.js')
  const toolbar = read('../src/components/TerminalToolbar.vue')
  const app = read('../src/App.vue')
  assert.match(catalog, /id: 'documents', label: 'Documents'/)
  assert.match(toolbar, /'open-documents'/)
  assert.match(toolbar, /documents: 'open-documents'/)
  assert.match(app, /@open-documents="openDocumentsDialog"/)
  assert.match(app, /<DocumentsDialog ref="documentsDialogRef"/)
})

test('Documents supports live Markdown preview and conflict revisions', () => {
  const dialog = read('../src/components/DocumentsDialog.vue')
  const api = read('../src/api/documentsApi.js')
  assert.match(dialog, /new MarkdownIt\(\{ html: false/)
  assert.match(dialog, /onDidChangeModelContent/)
  assert.match(dialog, /setTimeout\(\(\) => \{ this\.previewText = this\.sourceText \}, 150\)/)
  assert.match(dialog, /markdown\.render\(this\.editing \? this\.previewText/)
  assert.match(dialog, /:loading="saving" @click="save"/)
  assert.match(dialog, /sha256: this\.currentSha256/)
  assert.match(dialog, /await this\.askDiscard\(\)/)
  assert.match(api, /'PUT', payload/)
})


test('Documents enforces read-only state and guards unsaved editor content', () => {
  const dialog = read('../src/components/DocumentsDialog.vue')
  assert.match(dialog, /v-if="!editing && currentEditable"[^>]*>Edit<\/el-button>/)
  assert.match(dialog, /v-else-if="editing"/)
  assert.match(dialog, /if \(this\.saving \|\| this\.reading\) return/)
  assert.match(dialog, /if \(this\.editing\) this\.cancelEdit\(\)/)
  assert.match(dialog, /if \(requestId !== this\.documentRequestId \|\| !this\.visible\) return/)
  assert.match(dialog, /this\.documentRequestId\+\+/)
  assert.match(dialog, /if \(await this\.askDiscard\(\)\) this\.visible = false/)
})
