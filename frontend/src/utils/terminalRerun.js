import {
  isTerminalRemoteUploadText,
  isTerminalRunScriptText,
} from '../composables/terminalMarkers.js'

// A display label is not necessarily a command accepted by the command input.
export function canRerunTerminalSource(source = {}) {
  const type = String(source.blockType || '').trim()
  const commandText = String(source.commandText || '').trim()
  const scriptName = String(source.script_name || source.scriptMeta?.script_name || '').trim()

  if (type === 'script') return !!scriptName
  if (type && type !== 'command') return false

  // Also handle historic blocks whose producer did not attach type metadata.
  if (!commandText || isTerminalRemoteUploadText(commandText) ||
      commandText.startsWith('[Artifact Send]') || isTerminalRunScriptText(commandText)) {
    return false
  }
  return true
}
