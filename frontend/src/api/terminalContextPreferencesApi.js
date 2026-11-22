import { createPreferenceState } from './preferenceState.js'

const state = createPreferenceState('/api/terminal/context-preferences', { field_ids: [] })

export const loadTerminalContextPreferences = () => state.load()
export const saveTerminalContextPreferences = (payload = {}) => state.save(payload)
export const subscribeTerminalContextPreferences = (subscriber) => state.subscribe(subscriber)
