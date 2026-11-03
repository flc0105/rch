<template>
  <el-dialog
    v-model="visible"
    title="Keychains"
    width="1160px"
    top="5vh"
    class="fixed-dialog keychain-dialog"
    modal-class="keychain-overlay"
    @closed="handleClosed"
  >
    <div class="fixed-dialog-body keychain-body" v-loading="loading">
<!--      <div class="keychain-notice">-->
<!--        <el-alert-->
<!--          type="info"-->
<!--          show-icon-->
<!--          :closable="false"-->
<!--          title="Personal operations only: this manager is for manually saving credentials you own, similar to a local password manager integrated into this ops platform."-->
<!--        />-->
<!--      </div>-->

      <div class="keychain-toolbar">
        <div class="keychain-toolbar-left">
          <el-button
            size="small"
            :loading="loading"
            @click="loadKeychains"
          >
            Refresh
          </el-button>

          <el-button
            size="small"
            type="primary"
            @click="openCreateDialog"
          >
            New Credential
          </el-button>

          <el-button
            size="small"
            plain
            @click="openPasswordGeneratorDialog"
          >
            Generate Password
          </el-button>
        </div>

        <div class="keychain-toolbar-right">
          <div class="keychain-filter-box">
            <el-select
              v-model="machineIdFilter"
              size="small"
              clearable
              filterable
              placeholder="Filter by host"
              @change="handleMachineFilterChange"
            >
              <el-option
                v-for="item in machineOptions"
                :key="item.machine_id"
                :label="formatMachineOptionLabel(item)"
                :value="item.machine_id"
              />
            </el-select>
          </div>

          <div class="keychain-kind-filter-box">
            <el-select
              v-model="kindFilter"
              size="small"
              placeholder="All"
              @change="handleKindFilterChange"
            >
              <el-option label="All" value="" />
              <el-option label="Secrets" value="secret" />
              <el-option label="Logins" value="login" />
            </el-select>
          </div>

          <el-input
            v-model="searchText"
            size="small"
            clearable
            class="keychain-search"
            placeholder="Search credentials"
          />
        </div>
      </div>

      <div class="keychain-list-shell">
        <div
          v-if="!filteredItems.length && !loading"
          class="empty-state"
        >
          No credentials available
        </div>

        <div
          v-else
          class="keychain-card-grid"
        >
          <div
            v-for="row in filteredItems"
            :key="row.cred_id"
            class="keychain-card"
          >
            <div class="keychain-card-top">
              <div class="keychain-icon">
                {{ row.kind === 'secret' ? '🔑' : '🔐' }}
              </div>

              <div class="keychain-card-main">
                <div class="keychain-card-content">
                  <div class="keychain-title-row">
                    <div
                      class="keychain-name"
                      :title="row.name"
                    >
                      {{ row.name }}
                    </div>

                    <div class="keychain-tags">
                      <el-tag
                        size="small"
                        :type="row.kind === 'secret' ? 'warning' : 'primary'"
                        effect="plain"
                      >
                        {{ getKindLabel(row.kind) }}
                      </el-tag>

<!--                      <el-tag-->
<!--                        v-if="row.hostname"-->
<!--                        size="small"-->
<!--                        type="info"-->
<!--                      >-->
<!--                        {{ formatMachineOptionLabel(row) }}-->
<!--                      </el-tag>-->

<!--                      <el-tag-->
<!--                        v-if="row.site"-->
<!--                        size="small"-->
<!--                        type="success"-->
<!--                        effect="plain"-->
<!--                      >-->
<!--                        {{ row.site }}-->
<!--                      </el-tag>-->
                    </div>
                  </div>

                  <div class="keychain-field-grid">
                    <div
                      v-if="row.kind === 'login'"
                      class="keychain-field"
                    >
                      <div class="keychain-field-label">Username</div>
                      <div class="keychain-field-value mono">
                        {{ row.username || '-' }}
                      </div>
                    </div>

                    <div
                      class="keychain-field keychain-secret-field"
                      :class="{ 'keychain-field-wide': row.kind === 'secret' }"
                    >
                      <div class="keychain-field-label">
                        {{ row.kind === 'secret' ? 'Value' : 'Password' }}
                      </div>

                      <div class="keychain-field-value mono secret-inline">
                        <span
                          class="secret-value"
                          :class="{ masked: !isSecretVisible(row.cred_id) }"
                        >
                          {{ getVisibleSecretText(row) }}
                        </span>

                        <el-link
                          class="secret-action-link"
                          type="primary"
                          :underline="false"
                          :disabled="isSecretLoading(row.cred_id)"
                          @click="toggleCardSecret(row)"
                        >
                          {{
                            isSecretLoading(row.cred_id)
                              ? 'Loading...'
                              : (isSecretVisible(row.cred_id) ? 'Hide' : 'Show')
                          }}
                        </el-link>

                        <el-link
                          class="secret-action-link"
                          type="primary"
                          :underline="false"
                          :disabled="isSecretLoading(row.cred_id)"
                          @click="copyCardSecret(row)"
                        >
                          Copy
                        </el-link>
                      </div>
                    </div>
                  </div>

<!--                  <div-->
<!--                    v-if="row.note"-->
<!--                    class="keychain-note"-->
<!--                  >-->
<!--                    {{ row.note }}-->
<!--                  </div>-->
                </div>

                <div class="keychain-actions">
                  <el-button
                    size="small"
                    type="primary"
                    plain
                    @click="openDetailDialog(row)"
                  >
                    View
                  </el-button>

                  <el-button
                    size="small"
                    plain
                    @click="openEditDialog(row)"
                  >
                    Edit
                  </el-button>

                  <el-button
                    size="small"
                    type="danger"
                    plain
                    @click="deleteCredential(row)"
                  >
                    Delete
                  </el-button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <el-dialog
      v-model="editorVisible"
      :title="editorMode === 'edit' ? 'Edit Credential' : 'New Credential'"
      width="620px"
      top="6vh"
      append-to-body
      class="keychain-editor-dialog"
      modal-class="keychain-editor-overlay"
      @closed="resetEditor"
    >
      <el-form
        label-position="top"
        class="keychain-form"
      >
        <el-form-item label="Host Scope">
          <el-select
            v-model="form.machine_id"
            filterable
            placeholder="Select host"
            @change="handleFormMachineChange"
          >
            <el-option
              v-for="item in machineOptions"
              :key="item.machine_id"
              :label="formatMachineOptionLabel(item)"
              :value="item.machine_id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="Credential Type">
          <el-radio-group v-model="form.kind">
            <el-radio-button label="login">Logins</el-radio-button>
            <el-radio-button label="secret">Secrets</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="Cred Name">
          <el-input
            v-model="form.name"
            maxlength="160"
            placeholder="Credential name"
            show-word-limit
          />
        </el-form-item>

        <template v-if="form.kind === 'login'">
          <el-form-item label="Username">
            <el-input
              v-model="form.username"
              maxlength="256"
              placeholder="Username or email"
            />
          </el-form-item>

          <el-form-item label="Password">
            <el-input
              v-model="form.secret_value"
              type="password"
              show-password
              maxlength="4096"
              placeholder="Password"
            />
          </el-form-item>

          <el-form-item label="Site Optional">
            <el-input
              v-model="form.site"
              maxlength="512"
              placeholder="Site URL"
            />
          </el-form-item>
        </template>

        <template v-else>
          <el-form-item label="Value">
            <el-input
              v-model="form.secret_value"
              type="textarea"
              :rows="4"
              maxlength="65536"
              placeholder="Secret value"
            />
          </el-form-item>
        </template>

        <el-form-item label="Note Optional">
          <el-input
            v-model="form.note"
            type="textarea"
            :rows="3"
            maxlength="4096"
            placeholder="Short note"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="keychain-dialog-footer">
          <el-button @click="editorVisible = false">
            Cancel
          </el-button>
          <el-button
            type="primary"
            :loading="saving"
            @click="saveCredential"
          >
            Save
          </el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="detailVisible"
      title="Credential Details"
      width="620px"
      top="6vh"
      append-to-body
      class="keychain-detail-dialog"
      modal-class="keychain-detail-overlay"
      @closed="resetDetail"
    >
      <div
        v-if="detailItem"
        class="keychain-detail"
      >
        <div class="keychain-detail-title-row">
          <div class="keychain-detail-title">
            {{ detailItem.name }}
          </div>
          <el-tag
            size="small"
            :type="detailItem.kind === 'secret' ? 'warning' : 'primary'"
            effect="plain"
          >
            {{ getKindLabel(detailItem.kind) }}
          </el-tag>
        </div>

        <div class="keychain-detail-grid">
          <div class="keychain-detail-item keychain-detail-wide">
            <div class="keychain-detail-label">Host</div>
            <div class="keychain-detail-value mono">
              {{ formatMachineOptionLabel(detailItem) }}
            </div>
          </div>

          <template v-if="detailItem.kind === 'login'">
            <div class="keychain-detail-item keychain-detail-wide">
              <div class="keychain-detail-label">Site</div>
              <div class="keychain-detail-value">
                {{ detailItem.site || '-' }}
              </div>
            </div>

            <div class="keychain-detail-item">
              <div class="keychain-detail-label">Username</div>
              <div class="keychain-detail-value mono">
                {{ detailItem.username || '-' }}
              </div>
            </div>
          </template>

          <div
            class="keychain-detail-item"
            :class="{ 'keychain-detail-secret': detailItem.kind === 'secret' }"
          >
            <div class="keychain-detail-label">
              {{ detailItem.kind === 'secret' ? 'Value' : 'Password' }}
            </div>
            <div class="keychain-detail-value mono secret-inline">
              <span class="secret-value">
                {{ detailSecretVisible ? detailItem.secret_value : '••••••••' }}
              </span>
              <el-link
                class="secret-action-link"
                type="primary"
                :underline="false"
                @click="detailSecretVisible = !detailSecretVisible"
              >
                {{ detailSecretVisible ? 'Hide' : 'Show' }}
              </el-link>
              <el-link
                class="secret-action-link"
                type="primary"
                :underline="false"
                @click="copyDetailSecret"
              >
                Copy
              </el-link>
            </div>
          </div>

          <div class="keychain-detail-item">
            <div class="keychain-detail-label">Created</div>
            <div class="keychain-detail-value mono">
              {{ detailItem.created_at || '-' }}
            </div>
          </div>

          <div class="keychain-detail-item">
            <div class="keychain-detail-label">Last Modified</div>
            <div class="keychain-detail-value mono">
              {{ detailItem.updated_at || '-' }}
            </div>
          </div>

          <div
            v-if="detailItem.note"
            class="keychain-detail-item keychain-detail-note"
          >
            <div class="keychain-detail-label">Note</div>
            <div class="keychain-detail-value pre-wrap">
              {{ detailItem.note }}
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="keychain-dialog-footer">
          <el-button @click="detailVisible = false">
            Close
          </el-button>
          <el-button
            type="primary"
            plain
            @click="openEditDialog(detailItem)"
          >
            Edit
          </el-button>
        </div>
      </template>
    </el-dialog>

    <PasswordGeneratorDialog ref="passwordGeneratorDialogRef" />
  </el-dialog>
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import PasswordGeneratorDialog from './PasswordGeneratorDialog.vue'
import { listKeychains, getKeychainCredential, saveKeychainCredential, deleteKeychainCredential } from '../api/keychainsApi.js'

export default {
  name: 'KeychainManagerDialog',

  components: {
    PasswordGeneratorDialog,
  },

  props: {
    currentConnection: {
      type: Object,
      default: null,
    },

    machineAliasMap: {
      type: Object,
      default: () => ({}),
    },
  },

  data() {
    return {
      visible: false,
      loading: false,
      saving: false,
      items: [],
      machines: [],
      sharedMachineId: '__shared__',
      sharedHostname: 'Shared',
      machineIdFilter: '',
      kindFilter: '',
      searchText: '',
      visibleSecretMap: {},
      secretLoadingMap: {},
      editorVisible: false,
      editorMode: 'create',
      editingCredId: '',
      detailVisible: false,
      detailItem: null,
      detailSecretVisible: false,
      form: {
        machine_id: '',
        hostname: '',
        kind: 'login',
        name: '',
        username: '',
        secret_value: '',
        site: '',
        note: '',
      },
    }
  },

  computed: {
    machineOptions() {
      const map = {}
      const sharedId = this.sharedMachineId || '__shared__'
      map[sharedId] = {
        machine_id: sharedId,
        hostname: this.sharedHostname || 'Shared',
      }

      ;(this.machines || []).forEach(item => {
        if (!item || !item.machine_id) return
        map[item.machine_id] = item
      })

      return Object.values(map).sort((a, b) => {
        if (a.machine_id === sharedId) return -1
        if (b.machine_id === sharedId) return 1
        return this.formatMachineOptionLabel(a).localeCompare(this.formatMachineOptionLabel(b))
      })
    },

    filteredItems() {
      const query = String(this.searchText || '').trim().toLowerCase()
      const kind = String(this.kindFilter || '').trim()
      const list = (this.items || []).filter(item => !kind || item.kind === kind)
      if (!query) return list

      return list.filter(item => {
        const values = [
          item.name,
          item.username,
          item.site,
          item.note,
          item.hostname,
          item.machine_id,
          item.kind,
        ]
        return values.some(value => String(value || '').toLowerCase().includes(query))
      })
    },
  },

  methods: {
    buildEmptyForm() {
      return {
        machine_id: '',
        hostname: '',
        kind: 'login',
        name: '',
        username: '',
        secret_value: '',
        site: '',
        note: '',
      }
    },

    async open() {
      this.machineIdFilter = this.getCurrentMachineId() || this.sharedMachineId
      this.visible = true
      await this.loadKeychains()
    },

    isOpen() {
      return this.visible
    },

    async refreshIfOpen() {
      if (!this.visible) return
      await this.loadKeychains()
    },

    handleClosed() {
      this.items = []
      this.machines = []
      this.searchText = ''
      this.machineIdFilter = ''
      this.kindFilter = ''
      this.visibleSecretMap = {}
      this.secretLoadingMap = {}
    },

    normalizeMachineId(value) {
      return String(value || '').trim()
    },

    getCurrentMachineId() {
      return this.normalizeMachineId(this.currentConnection?.machine_id)
    },

    shortenMachineId(machineId) {
      const value = this.normalizeMachineId(machineId)
      if (!value) return '-'
      if (value === this.sharedMachineId) return 'shared'
      return value.length > 12 ? value.slice(0, 12) : value
    },

    getMachineAlias(machineId) {
      const id = this.normalizeMachineId(machineId)
      if (!id || id === this.sharedMachineId) return ''
      return String(this.machineAliasMap?.[id] || '').trim()
    },

    formatMachineOptionLabel(machine) {
      const machineId = this.normalizeMachineId(machine?.machine_id)
      if (!machineId) return '-'

      const shortId = this.shortenMachineId(machineId)
      const hostname = String(machine?.hostname || '').trim()
      const alias = this.getMachineAlias(machineId)
      if (alias) return `${alias} (${shortId})`
      return hostname ? `${shortId} (${hostname})` : shortId
    },

    resolveHostname(machineId) {
      const normalizedMachineId = this.normalizeMachineId(machineId)
      const matched = this.machineOptions.find(item => item.machine_id === normalizedMachineId)
      if (matched?.hostname) return matched.hostname
      if (normalizedMachineId === this.sharedMachineId) return this.sharedHostname
      return ''
    },

    getKindLabel(kind) {
      return kind === 'secret' ? 'Secrets' : 'Logins'
    },

    handleMachineFilterChange() {
      this.visibleSecretMap = {}
      this.loadKeychains()
    },

    handleKindFilterChange() {
      this.visibleSecretMap = {}
    },

    handleFormMachineChange() {
      this.form.hostname = this.resolveHostname(this.form.machine_id)
    },

    setFormKind(kind) {
      if (!['login', 'secret'].includes(kind)) return
      this.form.kind = kind
    },

    async loadKeychains() {
      this.loading = true

      try {
        const machineId = this.normalizeMachineId(this.machineIdFilter)
        const res = await listKeychains(machineId)
        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load keychains')
        }

        const data = json.data || {}
        this.items = Array.isArray(data.items) ? data.items : []
        this.machines = Array.isArray(data.machines) ? data.machines : []
        this.sharedMachineId = data.shared_machine_id || '__shared__'
        this.sharedHostname = data.shared_hostname || 'Shared'
      } catch (e) {
        this.items = []
        this.machines = []
        ElMessage.error(e.message || 'Failed to load keychains')
      } finally {
        this.loading = false
      }
    },

    async fetchCredential(credId) {
      const res = await getKeychainCredential(credId)
      const json = await res.json()
      if (!res.ok || json.code !== 0) {
        throw new Error(json.message || 'Failed to load credential')
      }
      return json.data?.item || null
    },

    isSecretVisible(credId) {
      return !!this.visibleSecretMap[credId]?.visible
    },

    isSecretLoading(credId) {
      return !!this.secretLoadingMap[credId]
    },

    getVisibleSecretText(row) {
      const cached = this.visibleSecretMap[row.cred_id]
      if (cached?.visible) return cached.value || ''
      return row.secret_placeholder || '••••••••'
    },

    async toggleCardSecret(row) {
      if (!row?.cred_id) return

      if (this.visibleSecretMap[row.cred_id]?.visible) {
        const nextMap = { ...this.visibleSecretMap }
        delete nextMap[row.cred_id]
        this.visibleSecretMap = nextMap
        return
      }

      this.secretLoadingMap = { ...this.secretLoadingMap, [row.cred_id]: true }
      try {
        const item = await this.fetchCredential(row.cred_id)
        this.visibleSecretMap = {
          ...this.visibleSecretMap,
          [row.cred_id]: {
            visible: true,
            value: item?.secret_value || '',
          },
        }
      } catch (e) {
        ElMessage.error(e.message || 'Failed to reveal credential')
      } finally {
        const nextLoadingMap = { ...this.secretLoadingMap }
        delete nextLoadingMap[row.cred_id]
        this.secretLoadingMap = nextLoadingMap
      }
    },

    async copyTextToClipboard(text, successMessage = 'Copied') {
      const value = String(text || '')
      if (!value) {
        ElMessage.warning('Nothing to copy')
        return
      }

      try {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(value)
        } else {
          const textarea = document.createElement('textarea')
          textarea.value = value
          textarea.setAttribute('readonly', 'readonly')
          textarea.style.position = 'fixed'
          textarea.style.left = '-9999px'
          document.body.appendChild(textarea)
          textarea.select()
          document.execCommand('copy')
          document.body.removeChild(textarea)
        }

        ElMessage.success(successMessage)
      } catch (e) {
        ElMessage.error(e.message || 'Copy failed')
      }
    },

    async copyCardSecret(row) {
      if (!row?.cred_id) return

      this.secretLoadingMap = { ...this.secretLoadingMap, [row.cred_id]: true }
      try {
        const cached = this.visibleSecretMap[row.cred_id]
        const value = cached?.value ?? (await this.fetchCredential(row.cred_id))?.secret_value
        await this.copyTextToClipboard(value, `${row.kind === 'secret' ? 'Value' : 'Password'} copied`)
      } catch (e) {
        ElMessage.error(e.message || 'Copy failed')
      } finally {
        const nextLoadingMap = { ...this.secretLoadingMap }
        delete nextLoadingMap[row.cred_id]
        this.secretLoadingMap = nextLoadingMap
      }
    },

    copyDetailSecret() {
      if (!this.detailItem) return
      this.copyTextToClipboard(
        this.detailItem.secret_value || '',
        `${this.detailItem.kind === 'secret' ? 'Value' : 'Password'} copied`,
      )
    },

    openCreateDialog() {
      this.editorMode = 'create'
      this.editingCredId = ''
      this.form = this.buildEmptyForm()
      this.form.machine_id = this.machineIdFilter || this.getCurrentMachineId() || this.sharedMachineId
      this.form.hostname = this.resolveHostname(this.form.machine_id)
      this.editorVisible = true
    },

    openPasswordGeneratorDialog() {
      this.$refs.passwordGeneratorDialogRef?.open()
    },

    async openEditDialog(row) {
      if (!row?.cred_id) return

      try {
        const item = await this.fetchCredential(row.cred_id)
        if (!item) throw new Error('Credential not found')

        this.editorMode = 'edit'
        this.editingCredId = item.cred_id
        this.form = {
          machine_id: item.machine_id || this.sharedMachineId,
          hostname: item.hostname || this.resolveHostname(item.machine_id),
          kind: item.kind || 'login',
          name: item.name || '',
          username: item.username || '',
          secret_value: item.secret_value || '',
          site: item.site || '',
          note: item.note || '',
        }
        this.detailVisible = false
        this.editorVisible = true
      } catch (e) {
        ElMessage.error(e.message || 'Failed to open credential')
      }
    },

    async openDetailDialog(row) {
      if (!row?.cred_id) return

      try {
        const item = await this.fetchCredential(row.cred_id)
        if (!item) throw new Error('Credential not found')
        this.detailItem = item
        this.detailSecretVisible = false
        this.detailVisible = true
      } catch (e) {
        ElMessage.error(e.message || 'Failed to open credential')
      }
    },

    resetEditor() {
      this.saving = false
      this.editorMode = 'create'
      this.editingCredId = ''
      this.form = this.buildEmptyForm()
    },

    resetDetail() {
      this.detailItem = null
      this.detailSecretVisible = false
    },

    validateCredentialForm() {
      if (!this.form.machine_id) {
        ElMessage.warning('Please select a host scope')
        return false
      }

      if (!String(this.form.name || '').trim()) {
        ElMessage.warning('Cred name is required')
        return false
      }

      if (this.form.kind === 'login' && !String(this.form.username || '').trim()) {
        ElMessage.warning('Username is required')
        return false
      }

      if (!String(this.form.secret_value || '').trim()) {
        ElMessage.warning(this.form.kind === 'login' ? 'Password is required' : 'Value is required')
        return false
      }

      return true
    },

    buildSavePayload() {
      const payload = {
        machine_id: this.form.machine_id,
        hostname: this.resolveHostname(this.form.machine_id),
        kind: this.form.kind,
        name: String(this.form.name || '').trim(),
        note: String(this.form.note || '').trim(),
        secret_value: String(this.form.secret_value || ''),
      }

      if (this.form.kind === 'login') {
        payload.username = String(this.form.username || '').trim()
        payload.site = String(this.form.site || '').trim()
      }

      return payload
    },

    async saveCredential() {
      if (!this.validateCredentialForm()) return

      this.saving = true
      try {
        const isEdit = this.editorMode === 'edit' && this.editingCredId
        const res = await saveKeychainCredential(this.buildSavePayload(), isEdit ? this.editingCredId : '')
        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Save failed')
        }

        ElMessage.success(isEdit ? 'Credential updated' : 'Credential created')
        this.editorVisible = false
        await this.loadKeychains()
      } catch (e) {
        ElMessage.error(e.message || 'Save failed')
      } finally {
        this.saving = false
      }
    },

    async deleteCredential(row) {
      if (!row?.cred_id) {
        ElMessage.warning('Invalid credential')
        return
      }

      try {
        await ElMessageBox.confirm(
          `Delete credential "${row.name || row.cred_id}"?`,
          'Delete Credential',
          { type: 'warning', confirmButtonText: 'Delete', cancelButtonText: 'Cancel' },
        )

        const res = await deleteKeychainCredential(row.cred_id)
        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Delete failed')
        }

        ElMessage.success('Credential deleted')
        const nextMap = { ...this.visibleSecretMap }
        delete nextMap[row.cred_id]
        this.visibleSecretMap = nextMap
        await this.loadKeychains()
      } catch (e) {
        if (e === 'cancel' || e === 'close' || e?.toString?.().includes('cancel')) return
        ElMessage.error(e.message || 'Delete failed')
      }
    },
  },
}
</script>

<style scoped>
/* Keychains 是纯服务端凭证管理，不和 client 执行层交互。 */
.fixed-dialog-body {
  height: 100%;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.keychain-body {
  gap: 12px;
}

.keychain-notice {
  flex: 0 0 auto;
}

.keychain-notice :deep(.el-alert) {
  border-radius: 12px;
}

.keychain-toolbar {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  flex: 0 0 auto;
}

.keychain-toolbar-left,
.keychain-toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.keychain-toolbar-left {
  justify-content: flex-start;
}

.keychain-toolbar-right {
  justify-content: flex-end;
}

.keychain-toolbar-left :deep(.el-button) {
  height: 32px;
  min-height: 32px;
  margin: 0;
  padding-inline: 12px;
  border-radius: 10px;
}

.keychain-filter-box {
  width: 300px;
}

.keychain-kind-filter-box {
  width: 118px;
}

.keychain-search {
  width: 260px;
}

.keychain-filter-box :deep(.el-select),
.keychain-kind-filter-box :deep(.el-select),
.keychain-search :deep(.el-input__wrapper) {
  width: 100%;
}

.keychain-filter-box :deep(.el-select__wrapper),
.keychain-kind-filter-box :deep(.el-select__wrapper),
.keychain-search :deep(.el-input__wrapper) {
  min-height: 32px;
  height: 32px;
  border-radius: 10px;
  font-size: 12px;
}

.keychain-list-shell {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.keychain-card-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-auto-rows: minmax(190px, auto);
  gap: 12px;
  align-items: stretch;
  align-content: start;
}

.keychain-card {
  display: flex;
  flex-direction: column;
  align-self: stretch;
  min-height: 190px;
  height: 100%;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 14px;
  padding: 14px;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
}

.keychain-card-top {
  display: flex;
  align-items: stretch;
  gap: 10px;
  min-width: 0;
  height: 100%;
  flex: 1 1 auto;
}

.keychain-icon {
  flex: 0 0 auto;
  align-self: flex-start;
  font-size: 22px;
  line-height: 1;
  margin-top: 2px;
}

.keychain-card-main {
  min-width: 0;
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.keychain-card-content {
  flex: 1 1 auto;
  min-height: 0;
}

.keychain-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.keychain-name {
  min-width: 0;
  font-size: 15px;
  font-weight: 750;
  color: var(--text);
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.keychain-tags {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 6px;
  flex: 0 0 auto;
  max-width: 56%;
}

.keychain-field-grid {
  margin-top: 12px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 12px;
}

.keychain-field,
.keychain-detail-item {
  min-width: 0;
}

.keychain-field-label,
.keychain-detail-label {
  font-size: 11px;
  color: var(--muted-2);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.keychain-field-value,
.keychain-detail-value {
  margin-top: 3px;
  font-size: 12px;
  color: var(--text);
  line-height: 1.5;
  word-break: break-word;
}

.keychain-secret-field {
  min-width: 0;
}

.keychain-field-wide {
  grid-column: 1 / -1;
}

.secret-value {
  white-space: pre-wrap;
}

.secret-value.masked {
  letter-spacing: 0.08em;
}

.secret-inline {
  min-width: 0;
}

.secret-inline .secret-value {
  overflow-wrap: anywhere;
}

.secret-action-link {
  margin-left: 8px;
  vertical-align: baseline;
  font-size: 12px;
}

.keychain-note {
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: 12px;
  background: #f8fafc;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.keychain-actions {
  margin-top: auto;
  padding-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.keychain-actions :deep(.el-button) {
  margin: 0;
  height: 30px;
  min-height: 30px;
  border-radius: 10px;
}

.empty-state {
  padding: 32px 12px;
  color: var(--muted);
  text-align: center;
  font-size: 13px;
}

.keychain-form :deep(.el-select) {
  width: 100%;
}

.keychain-dialog-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.keychain-dialog-footer :deep(.el-button) {
  margin: 0;
}

.keychain-detail-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 14px;
}

.keychain-detail-title {
  min-width: 0;
  font-size: 18px;
  font-weight: 750;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.keychain-detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 14px;
}

.keychain-detail-secret,
.keychain-detail-note,
.keychain-detail-wide {
  grid-column: 1 / -1;
}

.pre-wrap {
  white-space: pre-wrap;
}

.mono {
  font-family: var(--mono);
}

@media (max-width: 960px) {
  .keychain-toolbar {
    grid-template-columns: 1fr;
  }

  .keychain-toolbar-left,
  .keychain-toolbar-right {
    width: 100%;
    justify-content: flex-start;
  }

  .keychain-card-grid {
    grid-template-columns: 1fr;
    grid-auto-rows: auto;
  }

  .keychain-card {
    min-height: 0;
  }
}

@media (max-width: 640px) {
  .keychain-toolbar-left,
  .keychain-toolbar-right {
    flex-wrap: wrap;
    align-items: stretch;
  }

  .keychain-toolbar-left :deep(.el-button),
  .keychain-filter-box,
  .keychain-kind-filter-box,
  .keychain-search {
    width: 100%;
  }

  .keychain-card {
    padding: 12px;
  }

  .keychain-card-top,
  .keychain-title-row {
    flex-direction: column;
  }

  .keychain-tags {
    justify-content: flex-start;
    max-width: 100%;
  }

  .keychain-field-grid,
  .keychain-detail-grid {
    grid-template-columns: 1fr;
  }

  .keychain-actions :deep(.el-button) {
    flex: 1 1 calc(50% - 8px);
  }
}
</style>

<style>
/* 桌面端：dialog 高度固定，卡片列表内部滚动。 */
.keychain-overlay .el-overlay-dialog {
  overflow: hidden !important;
}

.keychain-overlay .el-dialog {
  height: 78vh !important;
  max-height: 78vh !important;
  margin-top: 5vh !important;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
}

.keychain-overlay .el-dialog__header {
  flex: 0 0 auto !important;
}

.keychain-overlay .el-dialog__body {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  overflow: hidden !important;
  padding-top: 12px !important;
  padding-bottom: 12px !important;
}

.keychain-overlay .fixed-dialog-body {
  height: 100% !important;
  min-height: 0 !important;
  overflow: hidden !important;
  display: flex !important;
  flex-direction: column !important;
}

.keychain-editor-overlay .el-dialog,
.keychain-detail-overlay .el-dialog {
  margin-top: 6vh !important;
}

@media (max-width: 768px), (max-height: 720px) {
  .keychain-overlay .el-dialog,
  .keychain-editor-overlay .el-dialog,
  .keychain-detail-overlay .el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
    display: flex !important;
    flex-direction: column !important;
    overflow: hidden !important;
  }

  .keychain-overlay .el-dialog__header,
  .keychain-editor-overlay .el-dialog__header,
  .keychain-detail-overlay .el-dialog__header {
    flex: 0 0 auto !important;
    padding: 14px 16px 10px !important;
  }

  .keychain-overlay .el-dialog__body,
  .keychain-editor-overlay .el-dialog__body,
  .keychain-detail-overlay .el-dialog__body {
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow: auto !important;
    padding: 10px 12px 12px !important;
  }
}
</style>
