import { defineComponent, h, ref } from 'vue'
import { ElMessageBox, ElOption, ElSelect } from 'element-plus'
import { loadServerPreferences } from '../api/serverPreferencesApi.js'
import { pasteRemoteFiles, extractRemoteZip, inspectRemoteUpload } from '../api/remoteFilesApi.js'

const labels = { stop: 'Stop', skip: 'Skip', replace: 'Replace', merge: 'Merge', keep_both: 'Keep Both' }

async function expectData(response, label) {
  const json = await response.json()
  if (!response.ok || json.code !== 0) throw new Error(json.message || `${label} failed`)
  return json.data || {}
}

async function chooseConflict(conflict) {
  const actions = (conflict.allowed_actions || []).filter(key => labels[key])
  if (!actions.length) throw new Error('Unsupported destination conflict')
  const choice = ref('stop')
  const content = defineComponent({
    setup() {
      return () => h('div', [
        h('p', { style: 'overflow-wrap:anywhere' }, `A ${conflict.target_kind === 'directory' ? 'folder' : 'file'} already exists at ${conflict.target || 'the destination'}.`),
        h('p', 'Choose how to handle this conflict:'),
        h(ElSelect, {
          modelValue: choice.value,
          'onUpdate:modelValue': value => { choice.value = value },
          style: 'width:100%',
          'aria-label': 'Conflict action',
        }, () => actions.map(value => h(ElOption, { key: value, value, label: labels[value] }))),
        ...(actions.includes('merge') ? [h('p', 'Merge keeps destination-only files. Replace removes them.')] : []),
      ])
    },
  })
  try {
    await ElMessageBox({
      title: 'File conflict', message: h(content),
      confirmButtonText: 'Continue', cancelButtonText: 'Cancel',
      showCancelButton: true, closeOnClickModal: false, type: 'warning',
    })
    return choice.value
  } catch (_) {
    return null
  }
}

export async function conflictsEnabled() {
  const settings = await loadServerPreferences()
  return settings.ask_on_conflict === true
}

// null: prompt disabled; false: user stopped/cancelled; object: operation arguments.
export async function preparePasteConflicts(clientId, request) {
  if (!await conflictsEnabled()) return { conflict_policies: (request.paths || []).map(() => 'stop') }
  const preview = await expectData(await pasteRemoteFiles(clientId, { ...request, inspect: true }), 'Conflict inspection')
  const policies = (request.paths || []).map(() => 'stop')
  for (const conflict of (preview.conflicts || [])) {
    if (!Number.isInteger(conflict.index) || conflict.index < 0 || conflict.index >= policies.length) {
      throw new Error('Invalid conflict inspection result')
    }
    const answer = await chooseConflict(conflict)
    if (!answer || answer === 'stop') return false
    policies[conflict.index] = answer
  }
  return { conflict_policies: policies }
}

export async function prepareExtractConflict(clientId, request) {
  if (!await conflictsEnabled()) return { conflict_policy: 'stop' }
  const preview = await expectData(await extractRemoteZip(clientId, { ...request, inspect: true }), 'ZIP conflict inspection')
  const conflicts = preview.conflicts || []
  if (!conflicts.length) return { conflict_policy: 'stop' }
  const answer = await chooseConflict(conflicts[0])
  if (!answer || answer === 'stop') return false
  return { conflict_policy: answer }
}

export async function prepareUploadConflict(clientId, destinationDir, filename, { allowSkip = false, promptEnabled = null } = {}) {
  if (!(promptEnabled === null ? await conflictsEnabled() : promptEnabled)) return 'stop'
  const preview = await expectData(await inspectRemoteUpload(clientId, destinationDir, filename), 'Upload conflict inspection')
  const conflicts = preview.conflicts || []
  if (!conflicts.length) return 'stop'
  const answer = await chooseConflict(conflicts[0])
  return !answer || answer === 'stop' ? false : (answer === 'skip' && !allowSkip ? false : answer)
}
