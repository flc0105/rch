<template>
  <el-form-item
    v-if="isVisible"
    :label="fieldLabel"
    class="param-form-field"
  >
    <el-switch
      v-if="type === 'boolean'"
      :model-value="!!modelValue"
      :disabled="isDisabled"
      @update:model-value="$emit('update:modelValue', $event)"
    />

    <el-radio-group
      v-else-if="type === 'select' && control === 'button_group'"
      :model-value="modelValue"
      :disabled="isDisabled"
      class="param-form-button-group"
      @update:model-value="$emit('update:modelValue', $event)"
    >
      <el-radio-button
        v-for="option in options"
        :key="`${param.name}-${String(option)}`"
        :value="option"
      >
        {{ String(option) }}
      </el-radio-button>
    </el-radio-group>

    <el-select
      v-else-if="type === 'select'"
      :model-value="modelValue"
      :disabled="isDisabled"
      class="param-form-control"
      clearable
      @update:model-value="$emit('update:modelValue', $event)"
    >
      <el-option
        v-for="option in options"
        :key="`${param.name}-${String(option)}`"
        :label="String(option)"
        :value="option"
      />
    </el-select>

    <div v-else-if="type === 'path_list'" class="path-list-editor">
      <div
        v-for="(entry, index) in pathEntries"
        :key="index"
        class="path-list-row"
      >
        <el-switch
          :model-value="entry.enabled"
          :disabled="isDisabled"
          :aria-label="`Enable path ${index + 1}`"
          @update:model-value="changePathEntry(index, 'enabled', $event)"
        />
        <el-input
          :model-value="entry.path"
          :disabled="isDisabled || !entry.enabled"
          placeholder="/path/to/folder"
          class="path-list-input"
          @update:model-value="changePathEntry(index, 'path', $event)"
        />
        <el-button
          :aria-label="`Remove path ${index + 1}`"
          :disabled="isDisabled"
          @click="removePathEntry(index)"
        >
          <el-icon><Delete /></el-icon>
        </el-button>
      </div>
      <el-button plain class="path-list-add" :disabled="isDisabled" @click="addPathEntry">
        <el-icon><Plus /></el-icon>
        Add path
      </el-button>
    </div>

    <el-input-number
      v-else-if="type === 'integer' || type === 'number'"
      :model-value="numericModelValue"
      :min="numericMin"
      :max="numericMax"
      :placeholder="placeholder"
      :disabled="isDisabled"
      controls-position="right"
      class="param-form-control"
      @update:model-value="$emit('update:modelValue', $event)"
    />

    <el-input
      v-else-if="type === 'textarea'"
      :model-value="textModelValue"
      type="textarea"
      :rows="textareaRows"
      :placeholder="placeholder"
      :disabled="isDisabled"
      class="param-form-control"
      @update:model-value="$emit('update:modelValue', $event)"
    />

    <el-input
      v-else-if="isRemote"
      :model-value="remoteDisplayValue"
      :placeholder="placeholder"
      :disabled="isDisabled"
      class="param-form-control"
      readonly
    >
      <template #append>
        <el-button :disabled="isDisabled" @click="$emit('browse', param)">
          Browse
        </el-button>
      </template>
    </el-input>

    <el-input
      v-else
      :model-value="textModelValue"
      :placeholder="placeholder"
      :disabled="isDisabled"
      class="param-form-control"
      clearable
      @update:model-value="$emit('update:modelValue', $event)"
    />

    <div v-if="type === 'path_list'" class="hint-text param-form-hint">
      {{ param.description || 'No description' }}
      <template v-if="param.required"> · required</template>
    </div>
    <div v-else class="hint-text param-form-hint">
      {{ param.description || 'No description' }}
      <template v-if="param.required"> · required</template>
      <template v-if="hasDefault"> · default: {{ defaultDisplayValue }}</template>
      <template v-if="param.min !== undefined"> · min: {{ param.min }}</template>
      <template v-if="param.max !== undefined"> · max: {{ param.max }}</template>
    </div>
  </el-form-item>
</template>

<script>
import { isParamDisabled, isParamVisible, isRemoteMultiParam, isRemoteParam, normalizeParamControl, normalizeParamType } from '../utils/parameterSchema.js'
import { Delete, Plus } from '@element-plus/icons-vue'

export default {
  name: 'ParamFormField',
  components: { Delete, Plus },

  props: {
    param: {
      type: Object,
      required: true,
    },
    modelValue: {
      default: '',
    },
    formValues: {
      type: Object,
      default: () => ({}),
    },
  },

  emits: ['update:modelValue', 'browse'],

  computed: {
    type() {
      return normalizeParamType(this.param?.type)
    },

    control() {
      return normalizeParamControl(this.param?.control)
    },

    isVisible() {
      return isParamVisible(this.param, this.formValues)
    },

    isDisabled() {
      return isParamDisabled(this.param, this.formValues)
    },

    pathEntries() {
      return Array.isArray(this.modelValue)
        ? this.modelValue.map(entry => ({ path: String(entry?.path ?? ''), enabled: entry?.enabled !== false }))
        : []
    },

    fieldLabel() {
      const label = String(this.param?.label || this.param?.name || '').trim()
      return `${label}${this.param?.required ? ' *' : ''}`
    },

    placeholder() {
      return String(this.param?.description || this.param?.label || this.param?.name || '').trim()
    },

    options() {
      return Array.isArray(this.param?.options) ? this.param.options : []
    },

    isRemote() {
      return isRemoteParam(this.param)
    },

    numericModelValue() {
      if (this.modelValue === '' || this.modelValue === null || this.modelValue === undefined) return null
      const value = Number(this.modelValue)
      return Number.isNaN(value) ? null : value
    },

    numericMin() {
      return this.param?.min === undefined || this.param?.min === null ? undefined : Number(this.param.min)
    },

    numericMax() {
      return this.param?.max === undefined || this.param?.max === null ? undefined : Number(this.param.max)
    },

    textModelValue() {
      return this.modelValue === null || this.modelValue === undefined ? '' : String(this.modelValue)
    },

    textareaRows() {
      const rows = Number(this.param?.rows)
      return Number.isFinite(rows) && rows > 0 ? Math.floor(rows) : 6
    },

    remoteDisplayValue() {
      if (isRemoteMultiParam(this.param)) {
        return Array.isArray(this.modelValue) ? JSON.stringify(this.modelValue) : '[]'
      }
      return this.textModelValue
    },

    hasDefault() {
      return this.param && this.param.default !== undefined && this.param.default !== null
    },

    defaultDisplayValue() {
      const value = this.param?.default
      if (Array.isArray(value) || (value && typeof value === 'object')) return JSON.stringify(value)
      return String(value)
    },
  },

  methods: {
    changePathEntry(index, key, value) {
      const entries = this.pathEntries
      entries[index] = { ...entries[index], [key]: value }
      this.$emit('update:modelValue', entries)
    },
    addPathEntry() {
      this.$emit('update:modelValue', [...this.pathEntries, { path: '', enabled: true }])
    },
    removePathEntry(index) {
      this.$emit('update:modelValue', this.pathEntries.filter((_, i) => i !== index))
    },
  },
}
</script>

<style scoped>
.param-form-control {
  width: 100%;
}

.param-form-button-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 0;
  max-width: 100%;
}

.param-form-hint {
  margin-top: 6px;
  line-height: 1.5;
}
.path-list-editor { width: 100%; display: flex; flex-direction: column; gap: 8px; }
.path-list-row { display: flex; align-items: center; gap: 8px; width: 100%; }
.path-list-input { flex: 1; min-width: 0; }
.path-list-add { align-self: flex-start; }
</style>
