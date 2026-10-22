<template>
  <el-dialog
    :model-value="visible"
    title="Choose Icon"
    width="520px"
    class="shared-icon-picker-dialog"
    append-to-body
    @update:model-value="$emit('update:visible', $event)"
  >
    <el-input v-model="search" clearable placeholder="Search icon names..." aria-label="Search icon names" />
    <div class="shared-icon-picker-list">
      <div v-if="filteredIcons.length" class="shared-icon-picker-grid">
        <button
          v-for="name in filteredIcons"
          :key="name"
          type="button"
          class="shared-icon-picker-choice"
          :class="{ 'is-selected': name === modelValue }"
          :title="name"
          :aria-label="name"
          @click="choose(name)"
        >
          <component :is="iconComponents[name]" :size="23" aria-hidden="true" />
          <span>{{ name }}</span>
        </button>
      </div>
      <el-empty v-else description="No matching icons" :image-size="60" />
    </div>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">Cancel</el-button>
    </template>
  </el-dialog>
</template>

<script>
export default {
  name: 'IconPickerDialog',
  props: {
    visible: { type: Boolean, default: false },
    modelValue: { type: String, default: '' },
    icons: { type: Array, default: () => [] },
    iconComponents: { type: Object, default: () => ({}) },
  },
  emits: ['update:visible', 'select'],
  data() { return { search: '' } },
  computed: {
    filteredIcons() {
      const term = this.search.trim().toLocaleLowerCase().replace(/[\s_-]+/g, '')
      return this.icons.filter(name => this.iconComponents[name]
        && (!term || name.toLocaleLowerCase().replace(/-/g, '').includes(term)))
    },
  },
  methods: {
    choose(name) {
      if (!this.icons.includes(name) || !this.iconComponents[name]) return
      this.$emit('select', name)
      this.$emit('update:visible', false)
    },
  },
  watch: { visible(value) { if (value) this.search = '' } },
}
</script>

<style scoped>
.shared-icon-picker-list { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 12px 2px 4px; }
.shared-icon-picker-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.shared-icon-picker-choice { display: flex; flex-direction: column; align-items: center; gap: 6px; min-width: 0; padding: 10px 4px; border: 1px solid var(--el-border-color); border-radius: 8px; background: var(--el-fill-color-light); color: var(--el-text-color-primary); font: inherit; cursor: pointer; }
.shared-icon-picker-choice span { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.shared-icon-picker-choice:hover, .shared-icon-picker-choice.is-selected { border-color: var(--el-color-primary); color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
@media (max-width: 480px) { .shared-icon-picker-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
</style>
<style>
.shared-icon-picker-dialog.el-dialog { max-width: calc(100vw - 24px); height: min(62vh, calc(100dvh - 24px)); display: flex; flex-direction: column; }
.shared-icon-picker-dialog .el-dialog__header, .shared-icon-picker-dialog .el-dialog__footer { flex: 0 0 auto; }
.shared-icon-picker-dialog .el-dialog__body { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
</style>
