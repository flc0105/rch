<template>
  <div class="remote-breadcrumb-bar">
    <template v-if="items.length">
      <button
        v-for="(item, index) in items"
        :key="`breadcrumb-${index}-${item.path}`"
        type="button"
        class="remote-breadcrumb-item"
        :class="{ active: item.isCurrent }"
        :disabled="item.isCurrent"
        @click="$emit('navigate', item)"
      >
        <ChevronRight v-if="index > 0" :size="14" class="remote-breadcrumb-sep" aria-hidden="true" />
        <span>{{ item.label }}</span>
      </button>
    </template>
    <span v-else class="remote-breadcrumb-empty">No path</span>
  </div>
</template>

<script>
import { ChevronRight } from '@lucide/vue'
export default {
  components: { ChevronRight },
  name: 'RemoteFileNavigation',
  props: { items: { type: Array, required: true } },
  emits: ['navigate'],
}
</script>
