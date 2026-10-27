<template>
  <div
    v-if="currentConnection && displayFields.length"
    class="terminal-connection-context"
    role="list"
    aria-label="Connection context"
  >
    <div
      v-for="field in displayFields"
      :key="field.id"
      class="terminal-connection-context-tag"
      :class="field.id === 'status' ? `terminal-connection-context-status-${field.value}` : ''"
      role="listitem"
      :title="`${field.label}: ${field.value}`"
    >
      <component
        :is="iconComponents[field.icon]"
        :size="13"
        :stroke-width="1.9"
        class="terminal-connection-context-icon"
        aria-hidden="true"
      />
      <span class="terminal-connection-context-label">{{ field.label }}:</span>
      <span class="terminal-connection-context-value">{{ field.value }}</span>
    </div>
  </div>
</template>

<script>
import { loadTerminalContextPreferences } from '../api/terminalContextPreferencesApi.js'
import { CONNECTION_CONTEXT_FIELD_CATALOG, cloneConnectionContextPreferences, resolveConnectionContextValue } from '../data/connectionContextFields.js'
import { CONNECTION_CONTEXT_ICONS } from '../data/connectionContextIcons.js'

export default {
  name: 'TerminalConnectionContext',

  props: {
    currentConnection: {
      type: Object,
      default: null,
    },
    statusNowTick: {
      type: Number,
      default: () => Date.now(),
    },
  },

  data() {
    return {
      preferences: cloneConnectionContextPreferences(),
      preferenceRevision: 0,
    }
  },

  computed: {
    iconComponents() {
      return CONNECTION_CONTEXT_ICONS
    },
    displayFields() {
      const fieldsById = new Map(CONNECTION_CONTEXT_FIELD_CATALOG.map(field => [field.id, field]))
      return this.preferences.field_ids
        .map(id => fieldsById.get(id))
        .filter(Boolean)
        .map(field => ({
          ...field,
          value: resolveConnectionContextValue(field.id, this.currentConnection, this.statusNowTick),
        }))
    },
  },

  mounted() {
    this.reloadPreferences()
  },

  methods: {
    setPreferences(value) {
      this.preferenceRevision += 1
      this.preferences = cloneConnectionContextPreferences(value)
    },

    async reloadPreferences() {
      const revision = this.preferenceRevision
      try {
        const preferences = await loadTerminalContextPreferences()
        if (revision === this.preferenceRevision) this.setPreferences(preferences)
      } catch (_error) {
        if (revision === this.preferenceRevision) this.setPreferences({ field_ids: [] })
      }
    },
  },
}
</script>

<style scoped>
.terminal-connection-context {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding: 8px 0 0;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
  -webkit-overflow-scrolling: touch;
}

.terminal-connection-context::-webkit-scrollbar {
  display: none;
}

.terminal-connection-context-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: 0 0 auto;
  min-width: 0;
  max-width: 300px;
  padding: 4px 8px;
  border: 1px solid var(--terminal-line);
  border-radius: 7px;
  background: rgba(148, 163, 184, 0.07);
  color: var(--terminal-muted, #94a3b8);
  font-size: 11px;
  line-height: 1.25;
  white-space: nowrap;
}

.terminal-connection-context-icon {
  flex: 0 0 auto;
  color: var(--terminal-muted, #94a3b8);
}

.terminal-connection-context-label {
  color: var(--terminal-muted, #94a3b8);
}

.terminal-connection-context-value {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--terminal-text, #e2e8f0);
  font-weight: 600;
}

.terminal-connection-context-status-online .terminal-connection-context-value {
  color: #86efac;
}

.terminal-connection-context-status-stale .terminal-connection-context-value {
  color: #fcd34d;
}

.terminal-connection-context-status-offline .terminal-connection-context-value {
  color: #fca5a5;
}

@media (max-width: 960px) {
  .terminal-connection-context {
    width: 100%;
    max-width: 100%;
    min-width: 0;
    gap: 5px;
    padding: 7px 0 0;
    overflow-x: auto;
    overscroll-behavior-x: contain;
  }

  .terminal-connection-context-tag {
    max-width: 260px;
    padding: 4px 7px;
    font-size: 10px;
  }
}
</style>
