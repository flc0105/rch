export const TERMINAL_RUN_SCRIPT_PREFIX = '[Run Script]'
export const TERMINAL_REMOTE_UPLOAD_PREFIX = '[Remote Upload]'
export const TERMINAL_COMMAND_FINISHED_PREFIX = '[Command finished]'
export const TERMINAL_CANCEL_REQUESTED_PREFIX = '[Cancel requested]'
export const TERMINAL_COMMAND_FAILED_PREFIX = '[Command failed]'
export const TERMINAL_BACKGROUND_PREFIX = '[Background]'

export function isTerminalRunScriptText(text) {
  return String(text ?? '').trim().startsWith(TERMINAL_RUN_SCRIPT_PREFIX)
}

export function isTerminalRemoteUploadText(text) {
  return String(text ?? '').trim().startsWith(TERMINAL_REMOTE_UPLOAD_PREFIX)
}

export function isTerminalCommandFinishedText(text) {
  return String(text ?? '').trim().startsWith(TERMINAL_COMMAND_FINISHED_PREFIX)
}

export function isTerminalCancelRequestedText(text) {
  return String(text ?? '').trim().startsWith(TERMINAL_CANCEL_REQUESTED_PREFIX)
}

export function isTerminalCommandFailedText(text) {
  return String(text ?? '').trim().startsWith(TERMINAL_COMMAND_FAILED_PREFIX)
}

export function formatTerminalCommandFinishedLine(command = '', finishText = '') {
  const commandText = String(command || '').trim()
  const statusText = String(finishText || '').trim()
  const commandPart = commandText ? ` ${commandText}` : ''
  const statusPart = statusText ? ` (${statusText})` : ''
  return `${TERMINAL_COMMAND_FINISHED_PREFIX}${commandPart}${statusPart}`
}

export function formatTerminalCancelRequestedLine(taskId = '') {
  const normalizedTaskId = String(taskId || '').trim()
  return normalizedTaskId
    ? `${TERMINAL_CANCEL_REQUESTED_PREFIX} task=${normalizedTaskId}`
    : TERMINAL_CANCEL_REQUESTED_PREFIX
}

export function formatTerminalCommandFailedLine(message = '') {
  const normalizedMessage = String(message || 'unknown error').trim()
  return `${TERMINAL_COMMAND_FAILED_PREFIX} ${normalizedMessage}`
}