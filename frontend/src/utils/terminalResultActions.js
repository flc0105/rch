// A single Result action catalog for Terminal links. Reference-backed actions
// declare how to map their payload; JSON and Artifact actions use the same UI.
export const TERMINAL_RESULT_ACTIONS = Object.freeze({
  preview: {
    label: 'Preview',
    run: (terminal, item) => terminal.previewTerminalArtifact(item.line),
  },
  json: {
    label: 'View JSON',
    run: (terminal, item) => terminal.$emit('open-json', terminal.buildTerminalJsonOpenPayload(item)),
  },
  log: {
    label: 'View Log',
    referenceType: 'log_file',
    fromReference(ref, line, clientId) {
      const path = String(ref.path || '').trim()
      if (!path || !clientId) return null
      return {
        type: 'log', key: `log:${clientId}:${path}`, line,
        source: { clientId, path, title: String(ref.title || 'Client startup') },
      }
    },
    run: (terminal, item) => terminal.$emit('open-log-viewer', item.source),
  },
  kill_instance: {
    label: 'Kill Instance',
    referenceType: 'session_action',
    fromReference(ref, line) {
      // A destructive session action must use the original Result's Client ID.
      const clientId = String(line?.meta?.resultClientId || '').trim()
      if (ref.action !== 'kill_instance' || !clientId) return null
      return { type: 'kill_instance', key: `kill_instance:${clientId}`, line, clientId }
    },
    run: (terminal, item) => terminal.confirmKillInstance(item.clientId),
  },
})

export function getTerminalReferenceActions(line, selectedClientId = '') {
  const references = line?.meta?.resultReferences
  if (!Array.isArray(references)) return []
  const clientId = String(line?.meta?.resultClientId || selectedClientId || '').trim()
  const actions = []
  for (const reference of references) {
    if (!reference || typeof reference !== 'object') continue
    for (const definition of Object.values(TERMINAL_RESULT_ACTIONS)) {
      if (definition.referenceType !== reference.type) continue
      const action = definition.fromReference(reference, line, clientId)
      if (action) actions.push(action)
    }
  }
  return actions
}

export function getTerminalActionLabel(item) {
  return TERMINAL_RESULT_ACTIONS[item?.type]?.label || ''
}

export function executeTerminalAction(terminal, item) {
  return TERMINAL_RESULT_ACTIONS[item?.type]?.run?.(terminal, item)
}
