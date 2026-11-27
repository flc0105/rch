<template>
  <el-dropdown-item v-for="item in items" :key="item.command" :command="item.command" :disabled="disabled" :icon="remoteActionIcon(item.command)">
    {{ item.label }}
  </el-dropdown-item>
  <!-- <el-dropdown-item command="icloud">iCloud</el-dropdown-item> -->
</template>

<script>
import { remoteActionIcon } from '../utils/remoteFileIcons.js'
export default {
  methods: { remoteActionIcon },
  name: 'RemoteSystemJumpItems',
  props: { disabled: { type: Boolean, default: false } },
  data() {
    return { items: [
      { command: 'root', label: 'Root' },
      { command: 'home', label: 'Home' },
      { command: 'desktop', label: 'Desktop' },
      { command: 'documents', label: 'Documents' },
      { command: 'downloads', label: 'Downloads' },
      { command: 'temp', label: 'Temp' },
      { command: 'executable', label: 'Program Directory' },
    ] }
  },
}
</script>
