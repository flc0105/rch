<template>
  <ScreenViewDialog
    ref="screenViewDialogRef"
    :selected-id="clientId"
    :current-connection="connection"
    standalone
    @open-clipboard="openClipboardDialog"
  />
  <ClipboardDialog
    ref="clipboardDialogRef"
    :selected-id="clientId"
    :current-connection="connection"
  />
</template>

<script>
import ScreenViewDialog from './components/ScreenViewDialog.vue'
import ClipboardDialog from './components/ClipboardDialog.vue'
import { listConnections } from './api/connectionsApi.js'

export default {
  name: 'ScreenViewTab',
  components: { ScreenViewDialog, ClipboardDialog },
  data() {
    return {
      clientId: new URLSearchParams(window.location.search).get('screen_view_client') || '',
      connection: null,
    }
  },
  async mounted() {
    window.addEventListener('pagehide', this.releaseScreenViewOnUnload)
    if (!this.clientId) return
    // Each tab establishes its own authenticated session with the same Screen View component.
    try {
      const connections = await listConnections()
      this.connection = connections.find(item => String(item.client_id) === this.clientId) || null
    } catch (_error) {
      // The Screen View API still reports connection/auth errors to the user.
    }
    document.title = `Screen View · ${this.connection?.hostname || this.clientId}`
    await this.$refs.screenViewDialogRef?.open()
  },
  beforeUnmount() {
    window.removeEventListener('pagehide', this.releaseScreenViewOnUnload)
  },
  methods: {
    releaseScreenViewOnUnload() {
      const sessionId = this.$refs.screenViewDialogRef?.screenSessionId
      if (!sessionId) return
      // Closing a browser tab does not reliably run Vue unmount hooks.
      navigator.sendBeacon(`/api/screen-view/${encodeURIComponent(sessionId)}/close`)
    },
    openClipboardDialog(tab = 'get') {
      return this.$refs.clipboardDialogRef?.open(tab)
    },
  },
}
</script>
