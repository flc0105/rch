<template>
  <el-dialog
    :model-value="visible"
    :title="pickerTitle"
    width="720px"
    top="8vh"
    append-to-body
    class="fixed-dialog keychain-picker-dialog"
    modal-class="keychain-picker-overlay"
    @update:model-value="$emit('update:visible', $event)"
  >
    <div class="keychain-picker-body">
      <el-radio-group
        :model-value="scope"
        class="keychain-picker-scope"
        @update:model-value="changeScope"
      >
        <el-radio-button value="machine" :disabled="!normalizedMachineId">
          Current Machine
        </el-radio-button>
        <el-radio-button value="shared">
          Server Shared
        </el-radio-button>
      </el-radio-group>

      <el-input
        v-model="searchText"
        clearable
        class="keychain-picker-search"
        placeholder="Search credentials"
      />

      <el-table
        ref="itemsTableRef"
        v-loading="loading"
        :data="filteredItems"
        row-key="cred_id"
        highlight-current-row
        height="min(48vh, 420px)"
        :empty-text="emptyText"
        @current-change="selectedItem = $event"
        @row-dblclick="selectCredential"
      >
        <el-table-column label="Name" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="keychain-picker-name">{{ row.name }}</div>
            <div v-if="row.site" class="keychain-picker-secondary">{{ row.site }}</div>
          </template>
        </el-table-column>
        <el-table-column label="Type" width="100">
          <template #default="{ row }">
            {{ row.kind === 'login' ? 'Login' : 'Secret' }}
          </template>
        </el-table-column>
        <el-table-column v-if="kind === 'login'" label="Username" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.username || '—' }}</template>
        </el-table-column>
        <el-table-column label="Updated" width="150">
          <template #default="{ row }">{{ row.updated_at || row.created_at || '—' }}</template>
        </el-table-column>
      </el-table>

      <div class="keychain-picker-source">
        Source: {{ scope === 'shared' ? 'Server Shared' : (machineId || 'Current Machine') }}
      </div>
    </div>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">Cancel</el-button>
      <el-button
        type="primary"
        :disabled="!selectedItem || loading || selecting"
        :loading="selecting"
        @click="selectCredential(selectedItem)"
      >
        Select
      </el-button>
    </template>
  </el-dialog>
</template>

<script>
import { ElMessage } from 'element-plus'
import { listKeychains, getKeychainCredential } from '../api/keychainsApi.js'

const SHARED_MACHINE_ID = '__shared__'

export default {
  name: 'KeychainPicker',

  props: {
    visible: { type: Boolean, default: false },
    machineId: { type: [String, Number], default: '' },
    kind: { type: String, default: 'secret' },
  },

  emits: ['update:visible', 'select'],

  data() {
    return {
      scope: 'machine',
      items: [],
      selectedItem: null,
      searchText: '',
      loading: false,
      selecting: false,
      loadSequence: 0,
      selectSequence: 0,
    }
  },

  computed: {
    normalizedMachineId() {
      return String(this.machineId || '').trim()
    },

    normalizedKind() {
      return String(this.kind || 'secret').trim().toLowerCase()
    },

    pickerTitle() {
      return this.normalizedKind === 'login' ? 'Select Login Credential' : 'Select Secret'
    },

    filteredItems() {
      const query = String(this.searchText || '').trim().toLowerCase()
      if (!query) return this.items
      return this.items.filter((item) => [item.name, item.username, item.site, item.note]
        .some(value => String(value || '').toLowerCase().includes(query)))
    },

    emptyText() {
      if (this.loading) return 'Loading credentials…'
      if (this.scope === 'machine' && !this.normalizedMachineId) return 'No current machine is available'
      return 'No matching credentials'
    },
  },

  watch: {
    visible(value) {
      if (value) {
        this.scope = this.normalizedMachineId ? 'machine' : 'shared'
        this.searchText = ''
        this.selectedItem = null
        this.loadItems()
      } else {
        this.loadSequence += 1
        this.selectSequence += 1
        this.items = []
        this.selectedItem = null
        this.searchText = ''
        this.loading = false
        this.selecting = false
      }
    },

    machineId() {
      if (!this.visible) return
      this.loadSequence += 1
      this.selectSequence += 1
      this.selectedItem = null
      this.loadItems()
    },
  },

  methods: {
    async changeScope(value) {
      this.selectSequence += 1
      this.selecting = false
      this.scope = value === 'shared' ? 'shared' : 'machine'
      this.selectedItem = null
      this.searchText = ''
      await this.loadItems()
    },

    async loadItems() {
      const sequence = ++this.loadSequence
      const requestedMachineId = this.scope === 'shared' ? SHARED_MACHINE_ID : this.normalizedMachineId
      this.items = []
      this.selectedItem = null
      if (!requestedMachineId) {
        this.loading = false
        return
      }

      this.loading = true
      try {
        const response = await listKeychains(requestedMachineId)
        const payload = await response.json()
        if (!response.ok || payload.code !== 0) {
          throw new Error(payload.message || 'Failed to load credentials')
        }
        if (sequence !== this.loadSequence || !this.visible) return
        this.items = (Array.isArray(payload.data?.items) ? payload.data.items : [])
          .filter(item => item?.kind === this.normalizedKind)
      } catch (error) {
        if (sequence === this.loadSequence) {
          this.items = []
          ElMessage.error(error?.message || 'Failed to load credentials')
        }
      } finally {
        if (sequence === this.loadSequence) this.loading = false
      }
    },

    async selectCredential(row) {
      if (!row?.cred_id || this.selecting) return
      const sequence = ++this.selectSequence
      const requestedMachineId = this.scope === 'shared' ? SHARED_MACHINE_ID : this.normalizedMachineId
      if (!requestedMachineId) return

      this.selecting = true
      try {
        const response = await getKeychainCredential(row.cred_id)
        const payload = await response.json()
        if (!response.ok || payload.code !== 0) {
          throw new Error(payload.message || 'Failed to read credential')
        }
        if (sequence !== this.selectSequence || !this.visible) return

        const item = payload.data?.item
        if (!item || item.cred_id !== row.cred_id || item.machine_id !== requestedMachineId || item.kind !== this.normalizedKind) {
          throw new Error('Credential changed while the picker was open. Refresh and try again.')
        }
        this.$emit('select', item)
        this.$emit('update:visible', false)
      } catch (error) {
        if (sequence === this.selectSequence) ElMessage.error(error?.message || 'Failed to select credential')
      } finally {
        if (sequence === this.selectSequence) this.selecting = false
      }
    },
  },
}
</script>

<style scoped>
.keychain-picker-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}

.keychain-picker-scope {
  align-self: flex-start;
  max-width: 100%;
}

.keychain-picker-search {
  width: 100%;
}

.keychain-picker-name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
}

.keychain-picker-secondary,
.keychain-picker-source {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.keychain-picker-source {
  padding-top: 2px;
}

@media (max-width: 640px) {
  .keychain-picker-scope {
    display: flex;
    width: 100%;
  }

  .keychain-picker-scope :deep(.el-radio-button) {
    flex: 1;
  }

  .keychain-picker-scope :deep(.el-radio-button__inner) {
    width: 100%;
  }
}
</style>
