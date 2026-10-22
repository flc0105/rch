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
    // Consume the device identity passed by the opener before querying the connection list.
    // This is display-only data; the Screen View request still uses the selected client ID.
    const tabName = window.name
    window.name = ''
    try {
      const snapshot = JSON.parse(tabName || 'null')
      if (snapshot?.screen_view_client === this.clientId) {
        this.connection = {
          client_id: this.clientId,
          hostname: String(snapshot.hostname || '').trim(),
          machine_id: String(snapshot.machine_id || '').trim(),
        }
      }
    } catch (_error) {
      // Directly opened tabs can still resolve identity from the Server.
    }
    // Each tab establishes its own authenticated session with the same Screen View component.
    try {
      const connections = await listConnections()
      this.connection = connections.find(item => String(item.client_id) === this.clientId) || this.connection
    } catch (_error) {
      // The Screen View API still reports connection/auth errors to the user.
    }
    document.title = `Screen View · ${this.connection?.hostname || String(this.connection?.machine_id || '').slice(0, 12) || 'Device'}`
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
