import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { test } from 'node:test'

const file = resolve(dirname(fileURLToPath(import.meta.url)), '../src/components/BackgroundJobDetailDialog.vue')
const source = readFileSync(file, 'utf8')

test('Job Detail Files displays linked_at provided by the association VO', () => {
  const filesPanel = source.split('class="background-job-file-list"')[1]?.split('class="empty-state compact"')[0] || ''
  assert.match(filesPanel, /formatBytes\(file\.size\s*\|\|\s*0\)/)
  assert.match(filesPanel, /formatDateTimeStandard\(file\.linked_at\)/)
  assert.doesNotMatch(filesPanel, /file\.created_at/)
})

test('Job message dates still use their own created_at', () => {
  assert.match(source, /formatDateTimeStandard\(message\.created_at\)/)
})
