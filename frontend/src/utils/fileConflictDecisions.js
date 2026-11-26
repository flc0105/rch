import { defineComponent, h, ref } from 'vue'
import { ElCheckbox, ElMessageBox, ElOption, ElSelect } from 'element-plus'
const labels = { stop: 'Stop', skip: 'Skip', replace: 'Replace', merge: 'Merge', keep_both: 'Keep Both' }

export async function expectData(response, label) {
  const json = await response.json()
  if (!response.ok || json.code !== 0) throw new Error(json.message || `${label} failed`)
  return json.data || {}
}

export async function chooseConflict(conflict, scope = {}) {
  const actions = (conflict.allowed_actions || []).filter(key => labels[key])
  if (!actions.length) throw new Error('Unsupported destination conflict')
  // A remembered action is only valid for conflicts that actually allow it.
  if (actions.includes(scope.action)) return scope.action
  const choice = ref('stop')
  const applyToAll = ref(false)
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
        h(ElCheckbox, {
          modelValue: applyToAll.value,
          'onUpdate:modelValue': value => { applyToAll.value = value },
          style: 'margin-top:12px',
        }, () => 'Apply to all'),
        ...(actions.includes('merge') ? [h('p', actions.includes('replace') ? 'Merge replaces matching files and keeps destination-only files. Replace removes destination-only files.' : 'Merge replaces matching files and keeps destination-only files.')] : []),
      ])
    },
  })
  try {
    await ElMessageBox({
      title: 'File conflict', message: h(content),
      confirmButtonText: 'Continue', cancelButtonText: 'Cancel',
      showCancelButton: true, closeOnClickModal: false, type: 'warning',
    })
    if (applyToAll.value) scope.action = choice.value
    return choice.value
  } catch (_) {
    return null
  }
}

// Shared and Remote use the same operation-scoped decision collection.
export async function resolveConflictPolicies(conflicts, count, scope = {}) {
  const policies = Array(count).fill('stop')
  for (const conflict of conflicts || []) {
    if (!Number.isInteger(conflict.index) || conflict.index < 0 || conflict.index >= count) {
      throw new Error('Invalid conflict inspection result')
    }
    const answer = await chooseConflict(conflict, scope)
    if (!answer || answer === 'stop') return false
    policies[conflict.index] = answer
  }
  return policies
}

