<template>
  <el-dialog
    :model-value="Boolean(current)"
    :title="current?.title || 'Execution interaction'"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
    width="min(520px, 94vw)"
    append-to-body
  >
    <div v-if="current" class="execution-interaction">
      <p style="white-space: pre-wrap; overflow-wrap: anywhere">{{ current.message }}</p>
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
        {{ current?.kind === 'confirm' ? 'Approve' : 'Continue' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script>
import { answerInteraction, listPendingInteractions } from '../api/interactionApi.js'

export default {
  name: 'ExecutionInteractionDialog',
  data() {
    return { queue: [], inputValue: '', selectedValue: '', errorText: '', submitting: false }
  },
  computed: {
    current() { return this.queue[0] || null },
  },
  methods: {
    enqueue(request) {
      if (!request?.interaction_id) return
      if (this.queue.some(item => item.interaction_id === request.interaction_id)) return
      this.queue.push(request)
    },
    resolved(payload) {
      if (!payload?.interaction_id) return
      this.queue = this.queue.filter(item => item.interaction_id !== payload.interaction_id)
      this.inputValue = ''
      this.selectedValue = ''
      this.errorText = ''
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
          ...(approved && request.kind !== 'confirm' ? { value: request.kind === 'select' ? this.selectedValue : this.inputValue } : {}),
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
.interaction-error { color: var(--el-color-danger); font-size: 12px; }
</style>
