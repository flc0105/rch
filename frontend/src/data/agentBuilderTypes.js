// Canonical builder wire identities and UI labels; match backend/core/agent_build_contract.py.
export const AGENT_BUILDER = Object.freeze({
  PYTHON: 'python',
  GO: 'go',
  GO_LOADER: 'go_loader',
})

export const AGENT_BUILDER_LABEL = Object.freeze({
  [AGENT_BUILDER.PYTHON]: 'Python Bundle',
  [AGENT_BUILDER.GO]: 'Go',
  [AGENT_BUILDER.GO_LOADER]: 'Go Loader',
})

export function displayAgentBuilder(value) {
  return AGENT_BUILDER_LABEL[value] || value || '-'
}
