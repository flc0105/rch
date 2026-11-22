import { createPreferenceState } from './preferenceState.js'

const state = createPreferenceState('/api/toolbar/preferences', {
  toolbar: [], more: [], quick_actions_pinned: [], toolbox_shortcuts: [],
})

export const loadToolbarPreferences = () => state.load()
export const saveToolbarPreferences = (payload = {}) => state.save(payload)
export const subscribeToolbarPreferences = (subscriber) => state.subscribe(subscriber)
