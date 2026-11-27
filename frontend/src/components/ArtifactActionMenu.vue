<template>
  <el-dropdown
    trigger="click"
    @command="$emit('command', $event)"
  >
    <slot />
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item command="info">
          Info
        </el-dropdown-item>
        <el-dropdown-item command="rename">Rename</el-dropdown-item>
        <el-dropdown-item v-if="shared" command="move">Move to Folder</el-dropdown-item>
        <el-dropdown-item
          v-if="shared && !standaloneMode"
          command="send-current-device"
          :disabled="!selectedId"
        >
          {{ sendLabel }}
        </el-dropdown-item>
        <el-dropdown-item
          v-if="shared && !standaloneMode"
          command="send-current-device-clipboard"
          :disabled="!selectedId"
        >
          Send to Current Device Clipboard
        </el-dropdown-item>
        <el-dropdown-item
          command="delete"
          divided
        >
          Delete
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<script>
export default {
  name: 'ArtifactActionMenu',
  props: {
    shared: { type: Boolean, required: true },
    standaloneMode: { type: Boolean, required: true },
    selectedId: { type: [String, Number], required: true },
    sendLabel: { type: String, required: true },
  },
  emits: ['command'],
}
</script>
