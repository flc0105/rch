import { expectData, chooseConflict, resolveConflictPolicies } from './fileConflictDecisions.js'
import { loadServerPreferences } from '../api/serverPreferencesApi.js'
import { pasteRemoteFiles, extractRemoteZip, inspectRemoteUpload, inspectRemoteUploadPlan } from '../api/remoteFilesApi.js'

export async function conflictsEnabled() {
  const settings = await loadServerPreferences()
  return settings.ask_on_conflict === true
}

// null: prompt disabled; false: user stopped/cancelled; object: operation arguments.
export async function preparePasteConflicts(clientId, request) {
  if (!await conflictsEnabled()) return { conflict_policies: (request.paths || []).map(() => 'stop') }
  const preview = await expectData(await pasteRemoteFiles(clientId, { ...request, inspect: true }), 'Conflict inspection')
  const policies = await resolveConflictPolicies(preview.conflicts, (request.paths || []).length)
  return policies === false ? false : { conflict_policies: policies }
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

export async function prepareUploadConflict(clientId, destinationDir, filename, { allowSkip = false, promptEnabled = null, conflictScope = {} } = {}) {
  if (!(promptEnabled === null ? await conflictsEnabled() : promptEnabled)) return 'stop'
  const preview = await expectData(await inspectRemoteUpload(clientId, destinationDir, filename), 'Upload conflict inspection')
  const conflicts = preview.conflicts || []
  if (!conflicts.length) return 'stop'
  const answer = await chooseConflict(conflicts[0], conflictScope)
  return !answer || answer === 'stop' ? false : (answer === 'skip' && !allowSkip ? false : answer)
}

// Inspect the entire tree before mutating it; a skipped folder excludes its subtree.
export async function prepareRemoteUploadPlan(clientId, root, plan, isActive = () => true) {
  const prompt = await conflictsEnabled()
  const preview = await expectData(await inspectRemoteUploadPlan(clientId, root, plan.files.map(entry => entry.relativePath), plan.directories), 'Upload conflict inspection')
  const scope = {}, skipped = new Set(), reused = new Set()
  const excluded = path => [...skipped].some(dir => path === dir || path.startsWith(`${dir}/`))
  const requireActive = () => { if (!isActive()) throw new Error('Remote upload context changed') }
  const folderConflicts = [...(preview.folder_conflicts || [])].sort((a,b) => a.source.split('/').length - b.source.split('/').length)
  for (const conflict of folderConflicts) {
    requireActive()
    if (!plan.directories.includes(conflict.source)) throw new Error('Invalid folder conflict inspection result')
    if (excluded(conflict.source)) continue
    const answer = prompt ? await chooseConflict(conflict, scope) : (conflict.allowed_actions.includes('merge') ? 'merge' : 'stop')
    if (!answer || answer === 'stop') return false
    if (answer === 'skip') skipped.add(conflict.source)
    else if (answer === 'merge') reused.add(conflict.source)
    else throw new Error('Invalid folder conflict decision')
  }
  const policies = new Map()
  for (const conflict of preview.conflicts || []) {
    requireActive()
    if (plan.files[conflict.index]?.relativePath !== conflict.source) throw new Error('Invalid file conflict inspection result')
    if (excluded(conflict.source)) continue
    const answer = prompt ? await chooseConflict(conflict, scope) : 'stop'
    if (!answer || answer === 'stop') return false
    policies.set(conflict.source, answer)
  }
  requireActive()
  return { directories: plan.directories.filter(path => !excluded(path)), reused,
    files: plan.files.filter(entry => !excluded(entry.relativePath) && policies.get(entry.relativePath) !== 'skip')
      .map(entry => ({ ...entry, policy: policies.get(entry.relativePath) || 'stop' })) }
}
