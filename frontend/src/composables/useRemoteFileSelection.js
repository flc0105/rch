

export default {
  data() { return { remoteSelectedPaths: [] } },
  computed: {
    hasRemoteSelection() {
      return this.remoteSelectedPaths.length > 0
    },
    visibleRemoteSelectablePaths() {
      return this.displayRemoteFilesEntries
          .filter(row => this.isRemoteRowSelectable(row))
          .map(row => row.path)
    },
    isRemoteCurrentPageAllSelected() {
      const paths = this.visibleRemoteSelectablePaths

      if (!paths.length) return false

      return paths.every(path => this.remoteSelectedPaths.includes(path))
    },
  },
  methods: {
    isRemoteRowSelectable(row) {
      return !!(row && !row.is_parent_entry && row.path)
    },
    getRemoteSelectionTable() {
      return this.$refs?.remoteFilesTableRef
    },
    clearTableSelection() {
      const clear = () => this.getRemoteSelectionTable()?.clearSelection?.()
      clear()
      const requestSeq = this.remoteDirectoryRequestSeq
      this.$nextTick?.(() => {
        if (requestSeq === this.remoteDirectoryRequestSeq) clear()
      })
    },
    handleRemoteSelectionChange(rows) {
      this.remoteSelectedPaths = Array.isArray(rows)
          ? rows
              .filter(item => this.isRemoteRowSelectable(item))
              .map(item => item.path)
              .filter(Boolean)
          : []
    },
    toggleRemoteSelection(row) {
      if (!this.isRemoteRowSelectable(row)) return

      const exists = this.remoteSelectedPaths.includes(row.path)
      const table = this.getRemoteSelectionTable()

      if (exists) {
        this.remoteSelectedPaths = this.remoteSelectedPaths.filter(item => item !== row.path)
      } else {
        this.remoteSelectedPaths = [...this.remoteSelectedPaths, row.path]
      }
      table?.toggleRowSelection?.(row, !exists)
    },
    clearRemoteSelection() {
      this.remoteSelectedPaths = []
      this.clearTableSelection()
    },
    toggleRemoteCurrentPageSelection() {
      const paths = this.visibleRemoteSelectablePaths

      if (!paths.length) return

      if (this.isRemoteCurrentPageAllSelected) {
        this.remoteSelectedPaths = this.remoteSelectedPaths.filter(path => {
          return !paths.includes(path)
        })

        const table = this.getRemoteSelectionTable()

        if (table && typeof table.toggleRowSelection === 'function') {
          this.displayRemoteFilesEntries.forEach(row => {
            if (row && !row.is_parent_entry && row.path && paths.includes(row.path)) {
              table.toggleRowSelection(row, false)
            }
          })
        }

        return
      }

      const next = new Set(this.remoteSelectedPaths)

      paths.forEach(path => {
        next.add(path)
      })

      this.remoteSelectedPaths = Array.from(next)

      const table = this.getRemoteSelectionTable()

      if (table && typeof table.toggleRowSelection === 'function') {
        this.displayRemoteFilesEntries.forEach(row => {
          if (row && !row.is_parent_entry && row.path && paths.includes(row.path)) {
            table.toggleRowSelection(row, true)
          }
        })
      }
    },
  },
}
