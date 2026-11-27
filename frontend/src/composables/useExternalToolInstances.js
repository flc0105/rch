import { ElMessage, ElMessageBox } from 'element-plus'
import * as externalToolsApi from '../api/externalToolsApi.js'
import { formatDateTimeShort } from '../utils/formatters.js'

export default {
  data() {
    return {
      clientInstances: {},
    }
  },
  computed: {
    allInstances() {
      const rows = []
      for (const item of this.clientModules) {
        const byDevice = this.clientInstances || {}
        for (const [deviceId, toolMap] of Object.entries(byDevice)) {
          const list = toolMap?.[item.id] || []
          for (const instance of list) rows.push(this.normalizeInstanceRow(item, instance, deviceId))
        }
      }
      return rows.sort((a, b) => {
        if (a.running !== b.running) return a.running ? -1 : 1
        return String(b.started_at || '').localeCompare(String(a.started_at || ''))
      })
    },

    filteredInstances() {
      const keyword = String(this.searchText || '').trim().toLowerCase()
      const machine = this.normalizeMachineId(this.deviceFilter || this.defaultTargetValue())
      return this.allInstances.filter((row) => {
        if (machine && row.machine_id !== machine) return false
        if (!keyword) return true
        const values = [
          row.status,
          row.machine_id,
          row.machine_label,
          row.hostname,
          row.connection_id,
          row.tool_id,
          row.display_name,
          row.instance_id,
          row.pid,
          row.exec_path,
          row.config_path,
          row.stdout,
          row.pid_file,
          this.formatPortInfo(row),
        ].map(value => String(value || '').toLowerCase())
        return values.some(value => value.includes(keyword))
      })
    },
  },
  methods: {
    async refreshInstances(showToast = true) {
      const machineId = this.normalizeMachineId(this.deviceFilter || this.defaultTargetValue())
      const deviceId = this.getClientDeviceIdForMachine(machineId)
      if (!deviceId) {
        this.logExternalToolTarget('refresh-instances-skip', null, {
          reason: 'selected machine has no matching online client_id',
          selected_machine_id: machineId,
        })
        if (showToast) ElMessage.warning('Please select an online client')
        return
      }
      await this.loadAllClientInstances(deviceId, false)
      if (showToast) ElMessage.success('Instances refreshed')
    },

    groupInstancesByTool(items = []) {
  const grouped = {}
  for (const row of items || []) {
    const toolId = String(row?.tool_id || '').trim()
    if (!toolId) continue
    if (!grouped[toolId]) grouped[toolId] = []
    grouped[toolId].push(row)
  }
  return grouped
},

    normalizeInstanceByToolPayload(data = {}, modules = []) {
  if (data.by_tool && typeof data.by_tool === 'object') {
    const normalized = {}
    for (const item of modules || []) {
      if (item?.id) normalized[item.id] = []
    }
    for (const [toolId, rows] of Object.entries(data.by_tool || {})) {
      normalized[toolId] = Array.isArray(rows) ? rows : []
    }
    return normalized
  }

  const grouped = this.groupInstancesByTool(Array.isArray(data.items) ? data.items : [])
  for (const item of modules || []) {
    if (item?.id && !grouped[item.id]) grouped[item.id] = []
  }
  return grouped
},

    async loadAllClientInstances(deviceId = '', showToast = true) {
  const targetDeviceId = this.normalizeDeviceId(deviceId)
  if (!targetDeviceId || targetDeviceId === '__all__') return

  try {
    const data = await externalToolsApi.loadAllClientInstances(targetDeviceId, this.buildJsonHeaders())
    const nextToolMap = this.normalizeInstanceByToolPayload(data, this.clientModules)

    this.clientInstances = {
      ...this.clientInstances,
      [targetDeviceId]: nextToolMap,
    }

    if (showToast) ElMessage.success('Client instances refreshed')
  } catch (e) {
    if (showToast) ElMessage.error(e.message || 'Failed to load client instances')
    throw e
  }
},

    async loadClientInstances(toolId, deviceId = '', showToast = true) {
      const targetDeviceId = this.normalizeDeviceId(deviceId)
      if (!toolId || !targetDeviceId || targetDeviceId === '__all__') return
      try {
        const data = await externalToolsApi.loadClientInstances(targetDeviceId, toolId, this.buildJsonHeaders())
        this.clientInstances = {
          ...this.clientInstances,
          [targetDeviceId]: {
            ...(this.clientInstances[targetDeviceId] || {}),
            [toolId]: Array.isArray(data.items) ? data.items : [],
          },
        }
        if (showToast) ElMessage.success('Client instances refreshed')
      } catch (e) {
        if (showToast) ElMessage.error(e.message || 'Failed to load client instances')
      }
    },

    async startClientInstance(item, params, instanceId, installIfNeeded = false, deviceId = '', launcherOverride = null) {
      const targetDeviceId = this.normalizeDeviceId(deviceId || this.getActionDeviceId(this.getPackageForModule(item)))
      if (!targetDeviceId) throw new Error('Please select a target machine')

      const requestPlatform = this.getPlatformForConnectionId(targetDeviceId)
      const requestArch = this.getArchForConnectionId(targetDeviceId)
      this.logExternalToolTarget('start-client-instance', item, {
        request_client_id: targetDeviceId,
        request_platform: requestPlatform,
        request_arch: requestArch,
      })
      if (!requestPlatform || !requestArch) throw new Error(`Unable to resolve target platform/arch for client ${targetDeviceId}`)

      const requestPayload = {
        params,
        install_if_needed: false,
        platform: requestPlatform,
        arch: requestArch,
      }
      if (instanceId) requestPayload.instance_id = instanceId
      if (launcherOverride) requestPayload.launcher_override = launcherOverride

      const data = await externalToolsApi.startClientInstance(
        targetDeviceId,
        item.id,
        requestPayload,
        this.buildJsonHeaders(),
      )
      ElMessage.success(data?.message || 'Client instance started')
      await this.loadClientInstances(item.id, targetDeviceId, false)
    },

    async runClientOneshot(item, params, deviceId = '', launcherOverride = null) {
      const targetDeviceId = this.normalizeDeviceId(deviceId || this.getActionDeviceId(this.getPackageForModule(item)))
      if (!targetDeviceId) throw new Error('Please select a target machine')

      const requestPlatform = this.getPlatformForConnectionId(targetDeviceId)
      const requestArch = this.getArchForConnectionId(targetDeviceId)
      this.logExternalToolTarget('run-client-oneshot', item, {
        request_client_id: targetDeviceId,
        request_platform: requestPlatform,
        request_arch: requestArch,
      })
      if (!requestPlatform || !requestArch) throw new Error(`Unable to resolve target platform/arch for client ${targetDeviceId}`)

      const requestPayload = {
        params,
        platform: requestPlatform,
        arch: requestArch,
      }
      if (launcherOverride) requestPayload.launcher_override = launcherOverride

      const data = await externalToolsApi.runClientOneshot(
        targetDeviceId,
        item.id,
        requestPayload,
        this.buildJsonHeaders(),
      )
      await this.loadClientCatalogStatuses(targetDeviceId, false)
      return data || {}
    },

    normalizeInstanceRow(item, instance, deviceId = '') {
      const runtime = instance.runtime || {}
      const config = instance.config || {}
      const params = instance.params || {}
      const configPath = config.target || instance.config_file || ''
      const normalizedDeviceId = this.normalizeDeviceId(deviceId)
      const machineId = this.getMachineIdForConnectionId(normalizedDeviceId)
      const hostname = this.getHostnameForConnectionId(normalizedDeviceId)
      return {
        row_key: `client:${normalizedDeviceId}:${item.id}:${instance.instance_id}`,
        device_id: normalizedDeviceId,
        connection_id: normalizedDeviceId,
        machine_id: machineId,
        machine_label: this.getMachineLabel(machineId, normalizedDeviceId),
        hostname,
        tool_id: instance.tool_id || item.id,
        package_id: instance.package_id || item.package_id || '',
        module_id: instance.module_id || item.module_id || '',
        display_name: instance.display_name || item.display_name || item.id,
        instance_id: instance.instance_id || 'default',
        status: instance.status || 'unknown',
        running: !!instance.running,
        pid: instance.pid || '',
        exec_path: instance.exec_path || instance.executable_path || instance.argv?.[0] || runtime.argv?.[0] || '',
        config_path: configPath,
        stdout: instance.stdout || runtime.stdout || '',
        stderr: instance.stderr || runtime.stderr || '',
        pid_file: instance.pid_file || runtime.pid_file || '',
        state_file: instance.state_file || runtime.state_file || '',
        argv: instance.argv || runtime.argv || [],
        cwd: instance.cwd || runtime.cwd || '',
        params,
        started_at: instance.started_at || '',
        stopped_at: instance.stopped_at || '',
        module: item,
        raw: instance,
      }
    },

    formatPortInfo(row) {
  const params = row.params || {}

  // 1. 端口映射类，优先展示完整映射关系，比如 frpc。
  if (params.local_port || params.remote_port) {
    const localIp = params.local_ip || params.local_addr || params.local_host || '127.0.0.1'
    const localPort = params.local_port || '-'
    const remoteHost = params.remote_host || params.server_addr || 'server'
    const remotePort = params.remote_port || '-'
    return `${localIp}:${localPort} -> ${remoteHost}:${remotePort}`
  }

  // 2. 服务监听类，比如 filebrowser、http server、web ui。
  const listenPort =
    params.port ||
    params.listen_port ||
    params.http_port ||
    params.web_port ||
    params.ui_port ||
    params.dashboard_port ||
    params.rtsp_port ||
    params.hls_port ||
    params.webrtc_port

  if (listenPort) {
    const listenHost =
      params.address ||
      params.listen_addr ||
      params.listen_address ||
      params.host ||
      params.bind_addr ||
      params.bind_address ||
      params.ip ||
      '127.0.0.1'

    return `${listenHost}:${listenPort}`
  }

  // 3. 服务端 bind 类，比如 frps。
  if (params.bind_port) {
    const bindHost = params.bind_addr || params.bind_address || params.address || '0.0.0.0'
    return `${bindHost}:${params.bind_port}`
  }

  // 4. 控制端口类，比如 frpc 连接 frps 的 server_port。
  if (params.server_port) {
    const serverHost = params.server_addr || params.server_host || 'server'
    return `${serverHost}:${params.server_port}`
  }

  // 5. 如果 meta 里直接给了 URL，也可以显示。
  const url =
    params.url ||
    params.http_url ||
    params.web_url ||
    params.publish_url ||
    params.public_url

  if (url) return String(url)

  return '-'
},

    statusTagType(status) {
      const value = String(status || '').toLowerCase()
      if (value === 'running') return 'success'
      if (value === 'stale' || value === 'error') return 'danger'
      if (value === 'stopped') return 'info'
      return 'info'
    },

    shortTime(value) {
      return formatDateTimeShort(value)
    },

    async stopInstance(row) {
      try {
        await ElMessageBox.confirm(
          `Stop instance ${row.tool_id}/${row.instance_id}?`,
          'Stop External Tool Instance',
          { type: 'warning', confirmButtonText: 'Stop', cancelButtonText: 'Cancel' },
        )
      } catch (_) {
        return
      }
      try {
        await this.stopClientInstance(row)
        ElMessage.success(`Stop requested: ${row.instance_id}`)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to stop instance')
      }
    },

    async stopClientInstance(row) {
      const deviceId = this.normalizeDeviceId(row.device_id)
      if (!deviceId) throw new Error('Client instance row is missing device_id')
      await externalToolsApi.stopClientInstance(deviceId, row.tool_id, row.instance_id, {}, this.buildJsonHeaders())
      await this.loadClientInstances(row.tool_id, deviceId, false)
    },

    openInstanceLogs(row) {
      const clientId = this.normalizeDeviceId(row?.device_id)
      if (!clientId) {
        ElMessage.error('Client instance is missing a device id')
        return
      }
      this.$emit('open-log-viewer', {
        clientId,
        path: String(row.stdout || row.raw?.runtime?.stdout || '').trim(),
        title: `${row.tool_id}/${row.instance_id} logs`,
      })
    },

    openInstanceInfo(row) {
      const runtime = row.raw?.runtime || {}
      const params = row.params || {}
      this.showDetailDialog({
        title: `${row.tool_id}/${row.instance_id} info`,
        subtitle: row.machine_label || row.machine_id,
        copyText: row.exec_path || '',
        sections: [
          {
            title: 'Overview',
            rows: [
              { label: 'Machine', value: row.machine_label || row.machine_id },
              { label: 'Machine ID', value: row.machine_id, mono: true },
              { label: 'Connection ID', value: row.connection_id || '-', mono: true },
              { label: 'Hostname', value: row.hostname || '-' },
              { label: 'Tool', value: row.tool_id, mono: true },
              { label: 'Instance', value: row.instance_id, mono: true },
              { label: 'Status', value: row.status },
              { label: 'PID', value: row.pid || '-' },
              { label: 'Port', value: this.formatPortInfo(row), mono: true },
              { label: 'Started', value: this.shortTime(row.started_at) },
              { label: 'Stopped', value: this.shortTime(row.stopped_at) },
              { label: 'Message', value: row.raw?.message || '-' },
            ],
          },
          {
            title: 'Runtime paths',
            rows: [
              { label: 'Executable', value: row.exec_path || runtime.argv?.[0] || '-', mono: true },
              { label: 'CWD', value: row.cwd || runtime.cwd || '-', mono: true },
              { label: 'Config', value: row.config_path || '-', mono: true },
              { label: 'Log', value: row.stdout || '-', mono: true },
              { label: 'Stderr', value: row.stderr || '-', mono: true },
              { label: 'PID file', value: row.pid_file || '-', mono: true },
              { label: 'State file', value: row.state_file || '-', mono: true },
              { label: 'Argv', value: row.argv?.length ? row.argv : (runtime.argv || []), mono: true, multiline: true },
            ],
          },
          { title: 'Params', rows: [{ label: 'Runtime params', value: params, mono: true, multiline: true }] },
        ],
      })
    },

    canModifyStoppedInstanceFiles(row) {
      if (!row || row.running) return false
      const status = String(row.status || '').toLowerCase()
      return status === 'stopped' || status === 'not_started' || status === 'error'
    },

    canRestartInstance(row) {
      if (!row || row.running) return false
      const status = String(row.status || '').toLowerCase()
      return status === 'stopped' || status === 'not_started' || status === 'error'
    },

    handleInstanceMoreCommand(command, row) {
      if (command === 'info') return this.openInstanceInfo(row)
      if (command === 'restart') return this.restartInstance(row)
      if (command === 'clear_logs') return this.clearInstanceLogs(row)
      if (command === 'remove') return this.removeInstance(row)
      return null
    },

    async restartInstance(row) {
      if (!this.canRestartInstance(row)) {
        ElMessage.warning('Please stop this instance before restarting it')
        return
      }
      try {
        await ElMessageBox.confirm(
          `Restart instance ${row.tool_id}/${row.instance_id} with the same params?`,
          'Restart External Tool Instance',
          { type: 'warning', confirmButtonText: 'Restart', cancelButtonText: 'Cancel' },
        )
      } catch (_) {
        return
      }
      try {
        await this.startClientInstance(row.module, row.params || {}, row.instance_id, false, row.connection_id || row.device_id)
        ElMessage.success(`Restarted: ${row.instance_id}`)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to restart instance')
      }
    },

    async removeInstance(row) {
      if (!this.canModifyStoppedInstanceFiles(row)) {
        ElMessage.warning('Stop this instance first')
        return
      }
      try {
        await ElMessageBox.confirm(
          `Remove runtime files for instance ${row.tool_id}/${row.instance_id}?`,
          'Remove External Tool Instance',
          { type: 'warning', confirmButtonText: 'Remove', cancelButtonText: 'Cancel' },
        )
      } catch (_) {
        return
      }
      try {
        await this.removeClientInstance(row)
        ElMessage.success(`Removed: ${row.instance_id}`)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to remove instance')
      }
    },

    async removeClientInstance(row) {
      const deviceId = this.normalizeDeviceId(row.connection_id || row.device_id)
      if (!deviceId) throw new Error('Client instance row is missing connection_id/device_id')
      await externalToolsApi.removeClientInstance(deviceId, row.tool_id, row.instance_id, {}, this.buildJsonHeaders())
      await this.loadClientInstances(row.tool_id, deviceId, false)
    },

    async clearInstanceLogs(row) {
      if (!this.canModifyStoppedInstanceFiles(row)) {
        ElMessage.warning('Stop this instance first')
        return
      }
      try {
        await ElMessageBox.confirm(
          `Clear log file for instance ${row.tool_id}/${row.instance_id}?`,
          'Clear External Tool Logs',
          { type: 'warning', confirmButtonText: 'Clear Logs', cancelButtonText: 'Cancel' },
        )
      } catch (_) {
        return
      }
      try {
        await this.clearClientInstanceLogs(row)
        ElMessage.success(`Logs cleared: ${row.instance_id}`)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to clear logs')
      }
    },

    async clearClientInstanceLogs(row) {
      const deviceId = this.normalizeDeviceId(row.connection_id || row.device_id)
      if (!deviceId) throw new Error('Client instance row is missing connection_id/device_id')
      await externalToolsApi.clearClientInstanceLogs(deviceId, row.tool_id, row.instance_id, {}, this.buildJsonHeaders())
    },
  },
}
