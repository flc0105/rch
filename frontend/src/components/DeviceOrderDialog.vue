<template>
  <el-dialog
    v-model="visible"
    title="Reorder devices"
    width="min(480px, calc(100vw - 32px))"
    :close-on-click-modal="false"
    :close-on-press-escape="!saving"
    :show-close="!saving"
  >
    <p v-if="loading" role="status">Loading online devices…</p>
    <p v-else-if="error" role="alert" class="device-order-error">{{ error }}</p>
    <p v-else-if="!machines.length">No online devices</p>

    <ul v-if="machines.length" class="device-order-list" aria-label="Online devices">
      <li v-for="(machine, index) in machines" :key="machine.id" class="device-order-row">
        <span class="device-order-name">{{ machine.name }}</span>
        <span class="device-order-actions">
          <el-button
            size="small"
            title="Move up"
            :aria-label="`Move ${machine.name} up`"
            :disabled="saving || index === 0"
            @click="move(index, -1)"
          >↑</el-button>
          <el-button
            size="small"
            title="Move down"
            :aria-label="`Move ${machine.name} down`"
            :disabled="saving || index === machines.length - 1"
            @click="move(index, 1)"
          >↓</el-button>
        </span>
      </li>
    </ul>

    <template #footer>
      <el-button :disabled="saving" @click="visible = false">Cancel</el-button>
      <el-button type="primary" :loading="saving" :disabled="!changed" @click="save">Save</el-button>
    </template>
  </el-dialog>
</template>

<script>
import { listConnections, reorderOnlineDevices } from '../api/connectionsApi.js'

export default {
  name: 'DeviceOrderDialog',
  emits: ['order-saved'],

  data() {
    return {
      visible: false,
      loading: false,
      saving: false,
      error: '',
      machines: [],
      initialOrder: [],
    }
  },

  computed: {
    changed() {
      return this.machines.some((machine, index) => machine.id !== this.initialOrder[index])
    },
  },

  methods: {
    async open() {
      this.visible = true
      if (this.loading || this.saving) return

      this.loading = true
      this.error = ''
      this.machines = []
      this.initialOrder = []
      try {
        const onlineMachines = new Map()
        for (const connection of await listConnections()) {
          const id = String(connection.machine_id || '').trim().toLowerCase()
          if (!id || connection.connection_state !== 'online' || onlineMachines.has(id)) continue
          onlineMachines.set(id, {
            id,
            name: connection.machine_alias || connection.hostname || id,
            order: connection.machine_order ?? Number.MAX_SAFE_INTEGER,
          })
        }
        this.machines = Array.from(onlineMachines.values()).sort((a, b) => a.order - b.order || a.id.localeCompare(b.id))
        this.initialOrder = this.machines.map(machine => machine.id)
      } catch (error) {
        this.error = error.message || 'Failed to load online devices'
      } finally {
        this.loading = false
      }
    },

    move(index, direction) {
      const [machine] = this.machines.splice(index, 1)
      this.machines.splice(index + direction, 0, machine)
    },

    async save() {
      if (!this.changed || this.saving) return

      this.saving = true
      this.error = ''
      try {
        await reorderOnlineDevices(this.machines.map(machine => machine.id))
        this.visible = false
        this.$emit('order-saved')
      } catch (error) {
        this.error = error.message || 'Failed to save device order'
      } finally {
        this.saving = false
      }
    },
  },
}
</script>

<style scoped>
.device-order-list {
  max-height: min(52vh, 420px);
  overflow-y: auto;
  margin: 0;
  padding: 0;
  list-style: none;
}

.device-order-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 4px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.device-order-row:last-child {
  border-bottom: 0;
}

.device-order-name {
  overflow-wrap: anywhere;
}

.device-order-actions {
  flex-shrink: 0;
}

.device-order-error {
  color: var(--el-color-danger);
}
</style>
