import { getTerminalReplayAction } from './terminalOperation.js'

export function canRerunTerminalSource(source = {}) {
  return getTerminalReplayAction(source.operation || source) !== null
}
