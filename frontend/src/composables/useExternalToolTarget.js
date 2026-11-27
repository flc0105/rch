export default {
  data() {
    return {
      deviceFilter: '',
    }
  },
  computed: {
    currentClientPlatform() {
      return this.currentConnection?.os_alias || ''
    },

    currentClientArch() {
      return this.normalizeArch(this.currentConnection?.arch || '')
    },

    currentDeviceId() {
      return this.normalizeDeviceId(this.selectedId || this.currentConnection?.client_id || '')
    },

    currentMachineId() {
      return this.normalizeMachineId(this.currentConnection?.machine_id || '')
    },

    deviceFilterOptions() {
      const options = []
      const seen = new Set()
      for (const conn of this.connections || []) {
        const machineId = this.normalizeMachineId(conn?.machine_id)
        if (!machineId || seen.has(machineId)) continue
        seen.add(machineId)
        options.push({ value: machineId, label: this.formatMachineOptionLabel(conn) })
      }
      if (this.currentMachineId && !seen.has(this.currentMachineId)) {
        seen.add(this.currentMachineId)
        options.push({ value: this.currentMachineId, label: this.formatCurrentMachineLabel() })
      }
      return options
    },

    activeDeviceFilterLabel() {
      const value = this.normalizeDeviceId(this.deviceFilter)
      const option = this.deviceFilterOptions.find(item => item.value === value)
      if (option) return option.label
      if (!value) return 'current target'
      return this.shortenMachineId(value)
    },

    selectedTargetMachineId() {
      return this.normalizeMachineId(this.deviceFilter || this.defaultTargetValue())
    },

    selectedTargetClientId() {
      return this.getClientDeviceIdForMachine(this.selectedTargetMachineId)
    },

    selectedTargetPlatform() {
      return this.getPlatformForMachineId(this.selectedTargetMachineId)
    },

    selectedTargetArch() {
      return this.getArchForMachineId(this.selectedTargetMachineId)
    },
  },
  methods: {
    defaultTargetValue() {
      if (this.currentMachineId) return this.currentMachineId
      const first = (this.connections || []).find(conn => this.normalizeMachineId(conn?.machine_id))
      return this.normalizeMachineId(first?.machine_id || '')
    },

    getClientDeviceIdForMachine(machineId) {
      const id = this.normalizeMachineId(machineId)
      if (!id || id === '__all__') return ''
      const conn = this.findConnectionByMachineId(id)
      if (conn?.client_id) return this.normalizeDeviceId(conn.client_id)
      if (id === this.currentMachineId && this.currentDeviceId) return this.currentDeviceId
      const byConnectionId = this.findConnectionById(id)
      if (byConnectionId?.client_id) return this.normalizeDeviceId(byConnectionId.client_id)
      return ''
    },

    getPlatformForMachineId(machineId) {
      const id = this.normalizeMachineId(machineId)
      if (!id || id === '__all__') return ''
      const conn = this.findConnectionByMachineId(id) || (id === this.currentMachineId ? this.currentConnection : null)
      return conn?.os_alias || ''
    },

    getPlatformForConnectionId(deviceId) {
      const conn = this.findConnectionById(deviceId) || (this.normalizeDeviceId(deviceId) === this.currentDeviceId ? this.currentConnection : null)
      return conn?.os_alias || ''
    },

    getArchForMachineId(machineId) {
      const id = this.normalizeMachineId(machineId)
      if (!id || id === '__all__') return ''
      const conn = this.findConnectionByMachineId(id) || (id === this.currentMachineId ? this.currentConnection : null)
      return this.normalizeArch(conn?.arch || '')
    },

    getArchForConnectionId(deviceId) {
      const conn = this.findConnectionById(deviceId) || (this.normalizeDeviceId(deviceId) === this.currentDeviceId ? this.currentConnection : null)
      return this.normalizeArch(conn?.arch || '')
    },

    getActionDeviceId(item) {
      if (!item) return ''

      const machineId = this.selectedTargetMachineId
      if (!machineId || machineId === '__all__') return ''

      const deviceId = this.getClientDeviceIdForMachine(machineId)
      if (!deviceId) {
        this.logExternalToolTarget('resolve-client-id-missing', item, {
          reason: 'selected machine has no matching online client_id',
        })
      }
      return deviceId
    },

    normalizeDeviceId(value) {
      return String(value || '').trim()
    },

    normalizeMachineId(value) {
      return String(value || '').trim()
    },

    shortenDeviceId(deviceId) {
      const value = this.normalizeDeviceId(deviceId)
      if (!value) return '-'
      if (value === '__all__') return 'all'
      return value.length > 12 ? value.slice(0, 12) : value
    },

    shortenMachineId(machineId) {
      const value = this.normalizeMachineId(machineId)
      if (!value) return '-'
      if (value === '__all__') return 'all'
      return value.length > 12 ? value.slice(0, 12) : value
    },

    findConnectionById(deviceId) {
      const id = this.normalizeDeviceId(deviceId)
      return (this.connections || []).find(conn => this.normalizeDeviceId(conn?.client_id) === id) || null
    },

    findConnectionByMachineId(machineId) {
      const id = this.normalizeMachineId(machineId)
      return (this.connections || []).find(conn => this.normalizeMachineId(conn?.machine_id) === id) || null
    },

    getMachineIdForConnectionId(deviceId) {
      const conn = this.findConnectionById(deviceId)
      return this.normalizeMachineId(conn?.machine_id || (deviceId === this.currentDeviceId ? this.currentConnection?.machine_id : '') || deviceId)
    },

    getHostnameForConnectionId(deviceId) {
      const conn = this.findConnectionById(deviceId) || (deviceId === this.currentDeviceId ? this.currentConnection : null)
      return String(conn?.hostname || '').trim()
    },

    getMachineAlias(machineId) {
      const id = this.normalizeMachineId(machineId)
      if (!id) return ''
      return String(this.machineAliasMap?.[id] || '').trim()
    },

    formatMachineOptionLabel(conn) {
      const machineId = this.normalizeMachineId(conn?.machine_id)
      const shortId = this.shortenMachineId(machineId)
      const hostname = String(conn?.hostname || '').trim()
      const alias = this.getMachineAlias(machineId)
      if (alias) return `${alias} (${shortId})`
      return hostname ? `${shortId} (${hostname})` : shortId
    },

    formatCurrentMachineLabel() {
      const conn = this.currentConnection || this.findConnectionById(this.currentDeviceId)
      if (conn?.machine_id) return this.formatMachineOptionLabel(conn)
      return this.shortenMachineId(this.currentMachineId)
    },

    getMachineLabel(machineId, connectionId = '') {
      const id = this.normalizeMachineId(machineId)
      const conn = this.findConnectionByMachineId(id) || this.findConnectionById(connectionId)
      if (conn?.machine_id) return this.formatMachineOptionLabel(conn)
      if (id === this.currentMachineId && this.currentConnection) return this.formatMachineOptionLabel(this.currentConnection)
      return this.shortenMachineId(id)
    },

    getClientDeviceIdsForFilter(filterValue) {
      const value = this.normalizeMachineId(filterValue)
      if (!value) return []
      if (value === '__all__') {
        const ids = []
        const seen = new Set()
        for (const conn of this.connections || []) {
          const id = this.normalizeDeviceId(conn?.client_id)
          if (!id || seen.has(id)) continue
          seen.add(id)
          ids.push(id)
        }
        return ids
      }

      const ids = []
      const seen = new Set()
      for (const conn of this.connections || []) {
        const machineId = this.normalizeMachineId(conn?.machine_id)
        const clientId = this.normalizeDeviceId(conn?.client_id)
        if (!clientId || seen.has(clientId)) continue
        if (machineId === value || clientId === value) {
          seen.add(clientId)
          ids.push(clientId)
        }
      }
      if (!ids.length && value === this.currentMachineId && this.currentDeviceId) ids.push(this.currentDeviceId)
      return ids
    },

    logExternalToolTarget(action, item = null, extra = {}) {
      const selectedMachineId = this.selectedTargetMachineId
      const selectedClientId = this.getClientDeviceIdForMachine(selectedMachineId)

      const payload = {
        action,
        package_id: item?.package_meta?.id || item?.package_id || item?.id || '',
        selected_machine_id: selectedMachineId,
        selected_client_id: selectedClientId,
        current_device_id: this.currentDeviceId,
        current_machine_id: this.currentMachineId,
        selected_target_platform: this.selectedTargetPlatform,
        selected_target_arch: this.selectedTargetArch,
        current_client_platform: this.currentClientPlatform,
        current_client_arch: this.currentClientArch,
        ...extra,
      }

      console.info('[external-tools] target', payload)
      return payload
    },

    buildJsonHeaders(extra = {}) {
      if (typeof this.getTabScopedHeaders === 'function') {
        return this.getTabScopedHeaders(extra)
      }
      return extra
    },
  },
}
