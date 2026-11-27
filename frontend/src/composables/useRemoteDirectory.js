import { listRemoteDirectory, getRemoteSystemPaths } from '../api/remoteFilesApi.js'
import { ElMessage, ElMessageBox } from 'element-plus'
import { buildRemoteBreadcrumbItems } from '../utils/remotePaths.js'

export default {
  data() {
    return {
      remoteFilesLoading: false,
      remoteFilesContextSeq: 0,
      remoteDirectoryRequestSeq: 0,
      remoteDirectoryAbortController: null,
      remoteFilesCurrentPath: '',
      remoteFilesParentPath: '',
      remoteFilesEntries: [],
      remoteFilesPathInput: '',
      remoteFilesPage: 1,
      remoteFilesPageSize: 50,
      remoteFilesTotal: 0,
      remoteFilesTotalPages: 1,
      remoteFilesAllTotal: 0,
      remoteFilesHiddenTotal: 0,
      remoteSearchKeyword: '',
      remoteSearchRecursive: false,
      remoteSearchTimer: null,
      showHiddenFiles: false,
      quickJumpPaths: {},
      quickJumpLoading: false,
    }
  },
  beforeUnmount() {
    this.abortRemoteDirectoryRequest()
    this.clearRemoteSearchKeyword()
    this.remoteFilesContextSeq += 1
  },
  computed: {
    displayRemoteFilesEntries() {
      const entries = Array.isArray(this.remoteFilesEntries)
          ? this.remoteFilesEntries.filter(row => this.isRemoteDirectoryEntryVisible(row))
          : []

      if (!this.isRemoteSearchActive && this.remoteFilesParentPath && this.remoteFilesPage === 1) {
        entries.unshift({
          name: '..',
          path: this.remoteFilesParentPath,
          is_dir: true,
          is_symlink: false,
          is_hidden: false,
          size: 0,
          modified_at: '',
          is_parent_entry: true,
        })
      }

      return entries
    },
    remoteBreadcrumbItems() {
      const items = buildRemoteBreadcrumbItems(this.remoteFilesCurrentPath || '')

      return items.map(item => ({
        ...item,
        isCurrent: item.path === (this.remoteFilesCurrentPath || ''),
      }))
    },
    isRemoteSearchActive() {
      return !!this.normalizeRemoteSearchKeyword()
    },
  },
  methods: {
    normalizeRemoteSearchKeyword() {
      return String(this.remoteSearchKeyword || '').trim()
    },
    scheduleRemoteSearch() {
      if (this.remoteSearchTimer) {
        clearTimeout(this.remoteSearchTimer)
      }

      this.remoteSearchTimer = window.setTimeout(() => {
        this.applyRemoteSearch()
      }, 300)
    },
    async applyRemoteSearch() {
      if (this.remoteSearchTimer) {
        clearTimeout(this.remoteSearchTimer)
        this.remoteSearchTimer = null
      }

      await this.loadRemoteDirectory(this.remoteFilesCurrentPath || '', 1)
    },
    clearRemoteSearchKeyword() {
      if (this.remoteSearchTimer) {
        clearTimeout(this.remoteSearchTimer)
        this.remoteSearchTimer = null
      }

      this.remoteSearchKeyword = ''
    },
    async navigateRemoteDirectory(path) {
      this.clearRemoteSearchKeyword()
      await this.loadRemoteDirectory(path || '', 1)
    },
    async handleRemoteSearchRecursiveChange() {
      if (!this.isRemoteSearchActive) return
      await this.loadRemoteDirectory(this.remoteFilesCurrentPath || '', 1)
    },
    abortRemoteDirectoryRequest() {
      this.remoteDirectoryRequestSeq += 1
      const controller = this.remoteDirectoryAbortController
      this.remoteDirectoryAbortController = null
      if (controller) controller.abort()
    },
    async loadRemoteDirectory(path = '', page = 1) {
      const context = this.captureRemoteFilesContext()
      if (!context.clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      if (!this.visible) return
      this.abortRemoteDirectoryRequest()
      const requestSeq = ++this.remoteDirectoryRequestSeq
      const controller = new AbortController()
      this.remoteDirectoryAbortController = controller
      this.remoteFilesLoading = true

      try {
        const searchKeyword = this.normalizeRemoteSearchKeyword()
        const res = await listRemoteDirectory(context.clientId, { path, page, pageSize: this.remoteFilesPageSize, showHidden: this.showHiddenFiles, search: searchKeyword, recursive: this.remoteSearchRecursive }, { signal: controller.signal })
        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context) || requestSeq !== this.remoteDirectoryRequestSeq) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load remote directory')
        }

        const data = json.data || {}
        const pagination = data.pagination || {}
        const summary = data.summary || {}

        this.remoteFilesCurrentPath = data.current_path || ''
        this.remoteFilesParentPath = data.parent_path || ''
        this.remoteFilesEntries = Array.isArray(data.entries) ? data.entries : []
        this.remoteFilesPathInput = this.remoteFilesCurrentPath || ''
        this.remoteFilesPage = Number(pagination.page || page || 1)
        this.remoteFilesPageSize = Number(pagination.page_size || this.remoteFilesPageSize || 50)
        this.remoteFilesTotal = Number(pagination.total_visible || 0)
        this.remoteFilesTotalPages = Number(pagination.total_pages || 1)
        this.remoteFilesAllTotal = Number(summary.total_all || this.remoteFilesTotal || 0)
        this.remoteFilesHiddenTotal = Number(summary.total_hidden || 0)
        this.showHiddenFiles = !!summary.show_hidden
        this.remoteSelectedPaths = []
        this.clearTableSelection()
        this.onRemoteDirectoryLoaded?.()
      } catch (e) {
        if (e?.name === 'AbortError' || !this.isRemoteFilesContextActive(context) || requestSeq !== this.remoteDirectoryRequestSeq) return
        ElMessage.error(e.message || 'Failed to load remote directory')
      } finally {
        if (requestSeq === this.remoteDirectoryRequestSeq) {
          this.remoteDirectoryAbortController = null
          if (this.isRemoteFilesContextActive(context)) this.remoteFilesLoading = false
        }
      }
    },
    async refreshRemoteDirectory() {
      await this.loadRemoteDirectory(this.remoteFilesCurrentPath || '', this.remoteFilesPage || 1)
    },
    async goToRemoteParent() {
      if (!this.remoteFilesParentPath) return
      await this.navigateRemoteDirectory(this.remoteFilesParentPath)
    },
    async enterRemoteDirectory(row) {
      if (!row || !row.is_dir) return

      if (row.is_parent_entry) {
        await this.goToRemoteParent()
        return
      }

      await this.navigateRemoteDirectory(row.path)
    },
    async handleRemotePageChange(page) {
      await this.loadRemoteDirectory(this.remoteFilesCurrentPath || '', page || 1)
    },
    async handleRemotePageSizeChange(pageSize) {
      this.remoteFilesPageSize = Number(pageSize || 50)
      await this.loadRemoteDirectory(this.remoteFilesCurrentPath || '', 1)
    },
    async toggleRemoteHiddenFiles() {
      this.showHiddenFiles = !this.showHiddenFiles
      await this.loadRemoteDirectory(this.remoteFilesCurrentPath || '', 1)
    },
    async loadQuickJumpPaths() {
      const context = this.captureRemoteFilesContext()
      if (!context.clientId) return

      this.quickJumpLoading = true

      try {
        const res = await getRemoteSystemPaths(context.clientId)
        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (res.ok && json.code === 0 && json.data) {
          this.quickJumpPaths = json.data
        }
      } catch (e) {
        if (this.isRemoteFilesContextActive(context)) console.error('Failed to load system paths:', e)
      } finally {
        if (this.isRemoteFilesContextActive(context)) this.quickJumpLoading = false
      }
    },
    async jumpToSystemPath(command) {
      if (command === 'input_navigate') {
        await this.promptRemotePathNavigate()
        return
      }

      const path = this.quickJumpPaths[command]

      if (!path) {
        ElMessage.warning('Path not available')
        return
      }

      await this.navigateRemoteDirectory(path)
    },
    async promptRemotePathNavigate() {
      const context = this.captureRemoteFilesContext()
      try {
        const {value} = await ElMessageBox.prompt(
            'Enter the target path',
            'Go to Folder',
            {
              confirmButtonText: 'Go',
              cancelButtonText: 'Cancel',
              inputValue: this.remoteFilesCurrentPath || this.remoteFilesPathInput || '',
              inputPattern: /.+/,
              inputErrorMessage: 'Path is required',
            }
        )

        const path = String(value || '').trim()
        if (!path || !this.isRemoteFilesContextActive(context)) return

        this.remoteFilesPathInput = path
        await this.navigateRemoteDirectory(path)
      } catch (e) {
        if (e === 'cancel' || e === 'close' || e?.toString?.().includes('cancel') || !this.isRemoteFilesContextActive(context)) return
        ElMessage.error(e.message || 'Navigate failed')
      }
    },
    async goToRemoteBreadcrumb(item) {
      if (!item || !item.path || item.isCurrent) return
      await this.navigateRemoteDirectory(item.path)
    },
    resetRemoteDirectory() {
      this.abortRemoteDirectoryRequest()
      this.remoteFilesContextSeq += 1
      this.clearRemoteSearchKeyword()
      this.remoteFilesLoading = false
      this.remoteFilesCurrentPath = ''
      this.remoteFilesParentPath = ''
      this.remoteFilesEntries = []
      this.remoteFilesPathInput = ''
      this.remoteFilesPage = 1
      this.remoteFilesPageSize = 50
      this.remoteFilesTotal = 0
      this.remoteFilesTotalPages = 1
      this.remoteFilesAllTotal = 0
      this.remoteFilesHiddenTotal = 0
      this.remoteSearchRecursive = false
      this.showHiddenFiles = false
      this.quickJumpPaths = {}
      this.quickJumpLoading = false
      this.clearRemoteSelection()
    },
    isRemoteDirectoryEntryVisible(row) { return !!row },
    jumpToPath(command) { return this.jumpToSystemPath(command) },
  },
}
