<template>
  <el-form-item
    :label="fieldLabel"
    class="param-form-field"
  >
    <el-switch
      v-if="type === 'boolean'"
      :model-value="!!modelValue"
      @update:model-value="$emit('update:modelValue', $event)"
    />

    <el-select
      v-else-if="type === 'select'"
      :model-value="modelValue"
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

    <el-input-number
      v-else-if="type === 'integer' || type === 'number'"
      :model-value="numericModelValue"
      :min="numericMin"
      :max="numericMax"
      :placeholder="placeholder"
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
      class="param-form-control"
      @update:model-value="$emit('update:modelValue', $event)"
    />

    <el-input
      v-else-if="isRemote"
      :model-value="remoteDisplayValue"
      :placeholder="placeholder"
      class="param-form-control"
      readonly
    >
      <template #append>
        <el-button @click="$emit('browse', param)">
          Browse
        </el-button>
      </template>
    </el-input>

    <el-input
      v-else
      :model-value="textModelValue"
      :placeholder="placeholder"
      class="param-form-control"
      clearable
      @update:model-value="$emit('update:modelValue', $event)"
    />

    <div class="hint-text param-form-hint">
      {{ param.description || 'No description' }}
      <template v-if="param.required"> · required</template>
      <template v-if="hasDefault"> · default: {{ defaultDisplayValue }}</template>
      <template v-if="param.min !== undefined"> · min: {{ param.min }}</template>
      <template v-if="param.max !== undefined"> · max: {{ param.max }}</template>
    </div>
  </el-form-item>
</template>

<script>
import { isRemoteMultiParam, isRemoteParam, normalizeParamType } from '../utils/parameterSchema.js'

export default {
  name: 'ParamFormField',

  props: {
    param: {
      type: Object,
      required: true,
    },
    modelValue: {
      default: '',
    },
  },

  emits: ['update:modelValue', 'browse'],

  computed: {
    type() {
      return normalizeParamType(this.param?.type)
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
}
</script>

<style scoped>
.param-form-control {
  width: 100%;
}

.param-form-hint {
  margin-top: 6px;
  line-height: 1.5;
}
</style>
