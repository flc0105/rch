import { ElMessage, ElMessageBox } from 'element-plus'
import { listRemotePinnedPaths, saveRemotePinnedPath, deleteRemotePinnedPath } from '../api/remotePinsApi.js'

export default {
  data() {
    return {
      remotePinnedJumpItems: [],
      remotePinnedJumpLoading: false,
    }
  },
  computed: {
    hasPinnedQuickJumps() {
      return Array.isArray(this.remotePinnedJumpItems) && this.remotePinnedJumpItems.length > 0
    },
    currentPinnedQuickJumpItem() {
      const currentPath = String(this.remoteFilesCurrentPath || '').trim()
      if (!currentPath) return null

      return (this.remotePinnedJumpItems || []).find(item => {
        return String(item?.path || '').trim() === currentPath
      }) || null
    },
    remotePinButtonText() {
      return this.currentPinnedQuickJumpItem ? 'Unpin' : 'Pin'
    },
  },
  methods: {
    async loadPinnedQuickJumps() {
      const context = this.captureRemoteFilesContext()
      if (!context.clientId) return

      this.remotePinnedJumpLoading = true

      try {
        const res = await listRemotePinnedPaths(context.clientId)
        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (res.ok && json.code === 0 && json.data) {
          this.remotePinnedJumpItems = Array.isArray(json.data.items)
              ? json.data.items
              : []
        }
      } catch (e) {
        if (this.isRemoteFilesContextActive(context)) console.error('Failed to load pinned paths:', e)
      } finally {
        if (this.isRemoteFilesContextActive(context)) this.remotePinnedJumpLoading = false
      }
    },
    async promptSavePinnedQuickJump() {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      const currentPath = String(this.remoteFilesCurrentPath || '').trim()

      if (!currentPath) {
        ElMessage.warning('Current directory is empty')
        return
      }

      const currentItems = Array.isArray(this.remotePinnedJumpItems)
          ? this.remotePinnedJumpItems
          : []

      const currentPinnedItem = this.currentPinnedQuickJumpItem

      const currentDirectoryName = currentPath
          .replace(/[\\/]+$/, '')
          .split(/[\\/]/)
          .filter(Boolean)
          .pop() || 'Pinned Path'

      try {
        const {value} = await ElMessageBox.prompt(
            `Current path:<br><span style="word-break: break-all; color: var(--muted);">${this.escapeRemoteHtml(currentPath)}</span>`,
            currentPinnedItem ? 'Edit Pinned Path' : 'Pin Path',
            {
              confirmButtonText: currentPinnedItem ? 'Update' : 'Save',
              cancelButtonText: 'Cancel',
              dangerouslyUseHTMLString: true,
              inputValue: currentPinnedItem?.display_name || currentDirectoryName,
              inputPattern: /.+/,
              inputErrorMessage: 'Display name is required',
            }
        )

        const displayName = String(value || '').trim()
        if (!displayName || !this.isRemoteFilesContextActive(context)) return

        const exists = currentItems.find(item => {
          return (item?.display_name || '').trim() === displayName
        })

        if (
            exists &&
            (
                !currentPinnedItem ||
                (exists.display_name || '').trim() !== (currentPinnedItem.display_name || '').trim()
            )
        ) {
          await ElMessageBox.confirm(
              `A pinned path named "${this.escapeRemoteHtml(displayName)}" already exists. Update it to the current path?`,
              'Overwrite Pinned Path',
              {
                confirmButtonText: 'Overwrite',
                cancelButtonText: 'Cancel',
                type: 'warning',
                dangerouslyUseHTMLString: true,
              }
          )
        }

        const method = currentPinnedItem ? 'PUT' : 'POST'
        const body = currentPinnedItem
            ? {
              original_display_name: currentPinnedItem.display_name,
              display_name: displayName,
              path: currentPath,
            }
            : {
              display_name: displayName,
              path: currentPath,
            }

        if (!this.isRemoteFilesContextActive(context)) return
        const res = await saveRemotePinnedPath(clientId, body, method)

        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to save pinned path')
        }

        this.remotePinnedJumpItems = Array.isArray(json.data?.items)
            ? json.data.items
            : []

        ElMessage.success(json.data?.message || 'Pinned path saved')
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Failed to save pinned path')
      }
    },
    async deletePinnedQuickJump(item, options = {}) {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId || !item?.display_name) return false

      const shouldConfirm = options.confirm !== false

      try {
        if (shouldConfirm) {
          await ElMessageBox.confirm(
              `Remove pinned path "${this.escapeRemoteHtml(item.display_name)}"?`,
              'Delete Pinned path',
              {
                confirmButtonText: 'Delete',
                cancelButtonText: 'Cancel',
                type: 'warning',
                dangerouslyUseHTMLString: true,
              }
          )
        }

        if (!this.isRemoteFilesContextActive(context)) return false
        const res = await deleteRemotePinnedPath(clientId, item.display_name)

        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return false
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to delete pinned path')
        }

        this.remotePinnedJumpItems = Array.isArray(json.data?.items)
            ? json.data.items
            : []

        if (options.toast !== false) {
          ElMessage.success(json.data?.message || 'Pinned path removed')
        }

        return true
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return false
        if (this.isDialogCancel(e)) return false
        ElMessage.error(e.message || 'Failed to delete pinned path')
        return false
      }
    },
    async toggleCurrentPinnedQuickJump() {
      const currentItem = this.currentPinnedQuickJumpItem

      if (currentItem) {
        await this.deletePinnedQuickJump(currentItem)
        return
      }

      await this.promptSavePinnedQuickJump()
    },
    openPinnedQuickJumpManager() {
      const clientId = String((this.visible ? this.remoteFilesClientId : this.selectedId) || '').trim()
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }
      // The manager can open directly from Toolbox while Remote Files stays closed.
      if (!this.visible || this.remoteFilesClientId !== clientId) {
        this.remoteFilesContextSeq += 1
        this.remoteFilesClientId = clientId
        this.remotePinnedJumpItems = []
      }
      this.pinManagerVisible = true
      void this.loadPinnedQuickJumps()
    },
    handlePinnedQuickJumpsUpdated(items) {
      this.remotePinnedJumpItems = Array.isArray(items) ? items : []
    },
    async jumpToPath(command) {
      if (command && typeof command === 'object') {
        if (command.type === 'pinned_jump') {
          const path = String(command.path || '').trim()

          if (!path) {
            ElMessage.warning('Path not available')
            return
          }

          await this.navigateRemoteDirectory(path)
          return
        }
      }

      return this.jumpToSystemPath(command)
    },
  },
}
