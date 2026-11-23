import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { canUseTransferArtifact, transferArtifactDownloadUrl, transferDisplayName } from '../src/utils/transferCenter.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const drawer = read('../src/components/TransferCenterDrawer.vue')
const manager = read('../src/components/KeychainManagerDialog.vue')
const generator = read('../src/components/PasswordGeneratorDialog.vue')
const app = read('../src/App.vue')

const transfer = { state: 'completed', direction: 'client_to_server', artifact_id: 'a /⚿', filename: '/tmp/report.txt' }

test('Artifact actions follow v35 SSE eligibility; never offer for upload or failure', () => {
  assert.equal(canUseTransferArtifact(transfer), true)
  assert.equal(transferArtifactDownloadUrl(transfer), '/api/artifacts/a%20%2F%E2%9A%BF/download')
  for (const patch of [
    { direction: 'server_to_client' }, { state: 'failed' },
    { state: 'interrupted' }, { artifact_id: '' },
    { direction: 'browser_to_server' },
  ]) {
    const candidate = { ...transfer, ...patch }
    assert.equal(canUseTransferArtifact(candidate), false)
    assert.equal(transferArtifactDownloadUrl(candidate), '')
  }
})

test('Transfer Center shows filename only and exposes Info, conditional Preview and Download in More', () => {
  assert.equal(transferDisplayName(transfer), 'report.txt')
  assert.equal(transferDisplayName({ filename: 'C:\\dir\\foo.zip' }), 'foo.zip')
  assert.equal(transferDisplayName({}), 'File transfer')
  assert.doesNotMatch(drawer, /slice\(0, 50\)/)
  assert.match(drawer, /<MoreFilled\s*\/>/)
  assert.match(drawer, /<el-dropdown-item command="info">Info/)
  assert.match(drawer, /v-if="canUseArtifact\(transfer\)"/)
  assert.match(drawer, /<el-dropdown-item command="preview">Preview/)
  assert.match(drawer, /<el-dropdown-item command="download">Download/)
  assert.match(drawer, /<el-dropdown-item command="delete" divided>Delete/)
  assert.match(drawer, /label="Source Path"/)
  assert.match(drawer, /label="Destination Path"/)
  assert.match(app, /@preview-artifact="previewArtifact"/)
})

test('password generator can apply or save into the currently open Credential editor', () => {
  assert.match(manager, /:allow-apply="editorVisible"/)
  assert.match(manager, /@apply="applyGeneratedPassword"/)
  assert.match(manager, /@apply-save="saveGeneratedPassword"/)
  assert.match(manager, /this\.form\.secret_value = password/)
  assert.match(manager, /await this\.saveCredential\(\)/)
  assert.match(generator, /v-if="allowApply"/)
  assert.match(generator, /Use & Save/)
  assert.match(generator, /this\.\$emit\(save \? 'apply-save' : 'apply', this\.generatedPassword\)/)
})
