<template>
  <el-dialog
    :model-value="Boolean(current)"
    :title="current?.title || 'Execution interaction'"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
    :width="current?.kind === 'preview' ? 'min(820px, 96vw)' : 'min(520px, 94vw)'"
    append-to-body
  >
    <div v-if="current" class="execution-interaction">
      <p class="interaction-message">{{ current.message }}</p>
      <div v-if="current.kind === 'preview' && current.preview" class="execution-plan">
        <el-alert v-if="current.preview.notice" :title="current.preview.notice" type="warning" :closable="false" show-icon class="plan-notice" />
        <el-descriptions
          v-if="current.preview.summary?.length"
          :column="2"
          border
          size="small"
          class="plan-summary"
        >
          <el-descriptions-item
            v-for="item in current.preview.summary"
            :key="item.label"
            :label="item.label"
          >{{ item.value }}</el-descriptions-item>
        </el-descriptions>
        <el-table
          v-if="current.preview.rows?.length"
          :data="current.preview.rows"
          border
          stripe
          max-height="300"
          size="small"
          class="plan-table"
        >
          <el-table-column
            v-for="column in current.preview.columns"
            :key="column.key"
            :prop="column.key"
            :label="column.label"
            show-overflow-tooltip
            min-width="100"
          />
        </el-table>
        <div v-if="current.preview.switches?.length" class="plan-switches">
          <div v-for="item in current.preview.switches" :key="item.key" class="plan-switch-row">
            <div class="plan-switch-description">
              <strong>{{ item.label }}</strong>
              <div v-if="item.description" class="plan-switch-help">{{ item.description }}</div>
            </div>
            <el-switch v-model="switchValues[item.key]" active-text="On" inactive-text="Off" />
          </div>
          <el-alert v-if="switchValues.force === true" title="Force termination selected: process will receive SIGKILL without graceful shutdown." type="warning" :closable="false" show-icon />
        </div>
        <el-collapse v-if="current.preview.details?.length" class="plan-details">
          <el-collapse-item
            v-for="(detail, index) in current.preview.details"
            :key="index"
            :name="index"
            :title="detail.title"
          >
            <pre class="plan-detail-content">{{ detail.content }}</pre>
          </el-collapse-item>
        </el-collapse>
      </div>
      <el-input
        v-if="current.kind === 'input' || current.kind === 'secret'"
        v-model="inputValue"
        :type="current.kind === 'secret' ? 'password' : 'text'"
        :show-password="current.kind === 'secret'"
        :placeholder="current.placeholder || 'Enter value'"
        :autocomplete="current.kind === 'secret' ? 'off' : 'on'"
        @keyup.enter="submit(true)"
      />
      <el-select
        v-if="current.kind === 'select'"
        v-model="selectedValue"
        placeholder="Select an option"
        style="width: 100%"
      >
        <el-option v-for="option in current.options || []" :key="option" :label="option" :value="option" />
      </el-select>
      <p v-if="errorText" class="interaction-error">{{ errorText }}</p>
    </div>
    <template #footer>
      <el-button :disabled="submitting" @click="submit(false)">Reject / Cancel</el-button>
      <el-button type="primary" :loading="submitting" @click="submit(true)">
        {{ current?.kind === 'preview' ? (switchValues.force === true ? 'Approve force kill' : 'Approve plan') : current?.kind === 'confirm' ? 'Approve' : 'Continue' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script>
import { answerInteraction, listPendingInteractions } from '../api/interactionApi.js'

export default {
  name: 'ExecutionInteractionDialog',
  data() {
    return { queue: [], inputValue: '', selectedValue: '', switchValues: {}, errorText: '', submitting: false }
  },
  computed: {
    current() { return this.queue[0] || null },
  },
  methods: {
    initializeSwitches() {
      this.switchValues = Object.fromEntries(
        (this.current?.preview?.switches || []).map(item => [item.key, item.default === true])
      )
    },
    enqueue(request) {
      if (!request?.interaction_id) return
      if (this.queue.some(item => item.interaction_id === request.interaction_id)) return
      this.queue.push(request)
      if (this.queue.length === 1) this.initializeSwitches()
    },
    resolved(payload) {
      if (!payload?.interaction_id) return
      this.queue = this.queue.filter(item => item.interaction_id !== payload.interaction_id)
      this.inputValue = ''
      this.selectedValue = ''
      this.errorText = ''
      this.initializeSwitches()
    },
    async reloadPending(tabId) {
      if (!tabId) return
      try {
        const items = await listPendingInteractions(tabId)
        for (const item of items) this.enqueue(item)
      } catch (error) {
        console.warn('Unable to load pending interactions', error)
      }
    },
    async submit(approved) {
      const request = this.current
      if (!request || this.submitting) return
      if (approved && request.kind === 'select' && !(request.options || []).includes(this.selectedValue)) {
        this.errorText = 'Choose an option before continuing'
        return
      }
      this.submitting = true
      this.errorText = ''
      try {
        await answerInteraction(request.interaction_id, {
          approved,
          ...(approved && request.kind === 'preview' && request.preview?.switches?.length
            ? { value: Object.fromEntries(request.preview.switches.map(item => [item.key, this.switchValues[item.key] === true])) }
            : {}),
          ...(approved && !['confirm', 'preview'].includes(request.kind) ? { value: request.kind === 'select' ? this.selectedValue : this.inputValue } : {}),
        })
        this.resolved(request)
      } catch (error) {
        this.errorText = error?.message || 'Unable to submit interaction response'
      } finally {
        this.submitting = false
      }
    },
  },
}
</script>

<style scoped>
.interaction-message { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0 0 14px; }
.execution-plan { max-height: min(65vh, 620px); overflow-y: auto; }
.plan-notice { margin-bottom: 14px; }
.plan-summary { margin-bottom: 14px; }
.plan-table { margin-bottom: 10px; width: 100%; }
.plan-switches { padding: 12px; margin: 12px 0; border: 1px solid var(--el-border-color); border-radius: 6px; }
.plan-switch-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.plan-switch-description { flex: 1; font-size: 13px; }
.plan-switch-help { color: var(--el-text-color-secondary); font-size: 12px; margin-top: 4px; }
.plan-details { margin-top: 8px; }
.plan-detail-content { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; font-size: 12px; }
.interaction-error { color: var(--el-color-danger); font-size: 12px; }
</style>
