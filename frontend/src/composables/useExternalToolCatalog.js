import { ElMessage, ElMessageBox } from 'element-plus'
import * as externalToolsApi from '../api/externalToolsApi.js'
import { copyTextFallback } from '../utils/clipboard.js'
import { formatBytesHuman } from '../utils/formatters.js'
import { getModuleLauncher, getModuleExecution, isOneshotModule, formatExecutionLabel, getExecutionTagType, getRunButtonLabel } from '../utils/externalToolPresentation.js'

export default {
  data() {
    return {
      items: [],
      installStatuses: {},
      installLoading: false,
      packageOnlyCompatible: true,
      selectedPackageId: '',
    }
  },
  computed: {
    allModules() {
      const modules = []
      for (const pkg of this.items || []) {
        for (const module of this.getPackageModules(pkg)) {
          modules.push(module)
        }
      }
      return modules
    },

    clientModules() {
      return this.allModules || []
    },

    filteredModules() {
      const keyword = String(this.searchText || '').trim().toLowerCase()

      return (this.items || []).filter((item) => {
        if (this.packageOnlyCompatible && !this.isPackageAvailableForTarget(item)) return false
        if (!keyword) return true
        return this.moduleSearchText(item).includes(keyword)
      })
    },

    selectedPackage() {
      const list = this.filteredModules || []
      if (!list.length) return null
      const selectedId = String(this.selectedPackageId || '').trim()
      return list.find(item => item.id === selectedId) || list[0]
    },
  },
  methods: {
    getModuleLauncher, getModuleExecution, isOneshotModule, formatExecutionLabel, getExecutionTagType, getRunButtonLabel,
    async loadCatalog(showError = true) {
      try {
        const catalog = await externalToolsApi.loadExternalToolCatalog()
        this.items = Array.isArray(catalog.items) ? catalog.items : []
        if (!this.selectedPackageId && this.items.length) this.selectedPackageId = this.items[0].id || ''
      } catch (e) {
        if (showError) ElMessage.error(e.message || 'Failed to load external tools')
        throw e
      }
    },

    async loadClientCatalogStatuses(deviceId = '', showError = true) {
      const targetDeviceId = this.normalizeDeviceId(deviceId)
      if (!targetDeviceId || targetDeviceId === '__all__') return []

      const targetPlatform = this.getPlatformForConnectionId(targetDeviceId)
      const targetArch = this.getArchForConnectionId(targetDeviceId)
      this.logExternalToolTarget('client-catalog-request', null, {
        request_client_id: targetDeviceId,
        request_platform: targetPlatform,
        request_arch: targetArch,
      })
      if (!targetPlatform || !targetArch) {
        const message = `Unable to resolve target platform/arch for client ${targetDeviceId}`
        if (showError) ElMessage.error(message)
        throw new Error(message)
      }

      const targetItems = (this.items || []).filter(item => this.doesPackageBuildMatch(item, targetPlatform, targetArch))
      for (const item of targetItems) {
        const previous = this.installStatuses[this.installStatusKey(item, targetDeviceId)] || {}
        this.setInstallStatus(item, targetDeviceId, {
          ...previous,
          loading: true,
          error: '',
        })
      }

      try {
        const catalog = await externalToolsApi.loadClientExternalToolCatalog(
          targetDeviceId,
          {
            platform: targetPlatform,
            arch: targetArch,
          },
          this.buildJsonHeaders(),
        )
        const items = Array.isArray(catalog.items) ? catalog.items : []
        const seen = new Set()
        for (const item of items) {
          const status = item?.install_status
          const packageId = String(item?.id || status?.package_id || status?.tool_id || '').trim()
          if (!packageId) continue
          seen.add(packageId)
          if (status) {
            this.setInstallStatus(item, targetDeviceId, {
              ...status,
              loading: false,
              error: status.error || '',
            })
          }
        }
        for (const item of targetItems) {
          if (seen.has(String(item?.id || '').trim())) continue
          this.setInstallStatus(item, targetDeviceId, {
            tool_id: item.id,
            package_id: item.id,
            installed: false,
            loading: false,
            error: 'client status not returned',
            message: 'client status not returned',
          })
        }
        return Array.isArray(catalog.client_install_statuses) ? catalog.client_install_statuses : []
      } catch (e) {
        for (const item of targetItems) {
          this.setInstallStatus(item, targetDeviceId, {
            tool_id: item.id,
            package_id: item.id,
            installed: false,
            loading: false,
            error: e.message || 'Failed to load client install statuses',
            message: e.message || 'Failed to load client install statuses',
          })
        }
        if (showError) ElMessage.error(e.message || 'Failed to load client install statuses')
        return []
      }
    },

    getPackageById(packageId) {
      const id = String(packageId || '').trim()
      if (!id) return null
      return (this.items || []).find(item => String(item?.id || '').trim() === id) || null
    },

    normalizeModuleFromPackage(pkg, module) {
      if (!pkg || !module) return null
      const moduleId = String(module.id || module.module_id || '').trim()
      const toolId = String(module.tool_id || (moduleId ? `${pkg.id}.${moduleId}` : '')).trim()
      if (!toolId) return null
      return {
        ...module,
        id: toolId,
        tool_id: toolId,
        module_id: moduleId || toolId,
        package_id: pkg.id,
        package_meta: pkg,
        package: pkg.package || {},
        package_install: pkg.install || {},
        package_binaries: pkg.binaries || {},
        package_platforms: pkg.platforms || [],
        package_archs: pkg.archs || [],
        version: module.version || pkg.version || '',
        execution: this.getModuleExecution(module),
        platforms: pkg.platforms || module.platforms || [],
        archs: pkg.archs || module.archs || [],
      }
    },

    getPackageModules(pkg) {
      const result = []
      for (const module of pkg?.modules || []) {
        const normalized = this.normalizeModuleFromPackage(pkg, module)
        if (normalized) result.push(normalized)
      }
      return result
    },

    formatPackageModules(pkg) {
      return this.getPackageModules(pkg).map(module => module.display_name || module.module_id || module.id).join(', ')
    },

    getPackageForModule(module) {
      return module?.package_meta || this.getPackageById(module?.package_id || '') || module
    },

    canRunModuleAction(module) {
      const execution = this.getModuleExecution(module)
      if (!['daemon', 'oneshot'].includes(execution)) return false
      const pkg = this.getPackageForModule(module)
      if (!this.isPackageAvailableForTarget(pkg)) return false
      const deviceId = this.getActionDeviceId(pkg)
      const status = this.installStatuses[this.installStatusKey(pkg, deviceId)]
      return !!status?.installed
    },

    installStatusKey(itemOrToolId, deviceId = '') {
      const toolId = typeof itemOrToolId === 'object'
        ? (itemOrToolId?.package_meta?.id || itemOrToolId?.package_id || itemOrToolId?.id)
        : itemOrToolId
      return `${this.normalizeDeviceId(deviceId)}:${toolId || ''}`
    },

    getInstallStatusTargetLabel() {
      return 'This Client'
    },

    getModuleInstallDeviceId(item) {
      return this.getActionDeviceId(item)
    },

    getModuleInstallStatus(item) {
      if (!this.isPackageAvailableForTarget(item)) {
        return { label: 'Unavailable for target', type: 'info' }
      }
      const targetLabel = this.getInstallStatusTargetLabel()
      const deviceId = this.getModuleInstallDeviceId(item)
      if (!deviceId) return { label: 'Install: no client', type: 'info' }
      const status = this.installStatuses[this.installStatusKey(item, deviceId)]
      if (!status) return { label: `Status unknown on ${targetLabel}`, type: 'info' }
      if (status.loading) return { label: 'Checking...', type: 'info' }
      if (status.error) return { label: `Status unknown on ${targetLabel}`, type: 'info' }
      return status.installed
        ? { label: `Installed on ${targetLabel}`, type: 'success' }
        : { label: `Not installed on ${targetLabel}`, type: 'warning' }
    },

    setInstallStatus(itemOrToolId, deviceId, status) {
      const key = this.installStatusKey(itemOrToolId, deviceId)
      this.installStatuses = {
        ...this.installStatuses,
        [key]: { ...(status || {}) },
      }
    },

    async refreshInstallStatuses(showToast = false) {
      const deviceId = this.selectedTargetClientId
      if (!deviceId) {
        this.logExternalToolTarget('refresh-install-statuses-skip', null, {
          reason: 'no selectedTargetClientId',
        })
        if (showToast) ElMessage.warning('Please select an online client')
        return
      }
      await this.loadClientCatalogStatuses(deviceId, showToast)
      if (showToast) ElMessage.success('Install statuses refreshed')
    },

    isPackageAvailableForTarget(item) {
      if (!item) return false
      const pkg = item?.package_meta || item
      const deviceId = this.getActionDeviceId(pkg)
      const platform = this.selectedTargetPlatform
      const arch = this.selectedTargetArch
      return !!deviceId && !!platform && !!arch && this.doesPackageBuildMatch(pkg, platform, arch)
    },

    getPackageCurrentInstallStatus(item) {
      if (!item) return null
      const deviceId = this.getModuleInstallDeviceId(item)
      return this.installStatuses[this.installStatusKey(item, deviceId)] || null
    },

    canUsePackageAction(item) {
      return this.isPackageAvailableForTarget(item)
    },

    canInstallPackageAction(item) {
      if (!this.canUsePackageAction(item)) return false
      if (this.installLoading) return false
      const status = this.getPackageCurrentInstallStatus(item)
      if (status?.loading) return false
      return !status || status.installed !== true
    },

    async fetchInstallStatus(item, deviceId = '', options = {}) {
      if (!item?.id) return null
      const targetDeviceId = this.normalizeDeviceId(deviceId)
      if (!targetDeviceId) {
        this.logExternalToolTarget('fetch-install-status-skip', item, {
          reason: 'missing targetDeviceId',
          requested_device_id: deviceId,
        })
        return null
      }
      const statusKey = this.installStatusKey(item, targetDeviceId)
      const cachedStatus = this.installStatuses[statusKey]
      if (cachedStatus && !cachedStatus.loading && !cachedStatus.error && !options.force) return cachedStatus

      await this.loadClientCatalogStatuses(targetDeviceId, !options.silent)
      return this.installStatuses[statusKey] || null
    },

    normalizePlatform(value) {
      const text = String(value || '').trim().toLowerCase()
      const aliases = {
        windows: 'win',
        win32: 'win',
        darwin: 'mac',
        macos: 'mac',
        osx: 'mac',
        linux: 'linux',
        ios: 'ios',
        common: '*',
        all: '*',
        '*': '*',
      }
      return aliases[text] || text
    },

    normalizeArch(value) {
      const text = String(value || '').trim().toLowerCase().replace(/-/g, '_')
      const aliases = {
        x86_64: 'amd64',
        amd64: 'amd64',
        i386: '386',
        i686: '386',
        aarch64: 'arm64',
        arm64: 'arm64',
        all: '*',
        common: '*',
        '*': '*',
      }
      return aliases[text] || text
    },

    normalizeArchs(archs) {
      const source = Array.isArray(archs)
        ? archs
        : (typeof archs === 'string' && archs.trim() ? [archs] : [])
      const result = []
      const seen = new Set()
      source.forEach((arch) => {
        const normalized = this.normalizeArch(arch)
        if (!normalized || seen.has(normalized)) return
        seen.add(normalized)
        result.push(normalized)
      })
      return result.length ? result : ['*']
    },

    normalizePlatforms(platforms) {
      const source = Array.isArray(platforms)
        ? platforms
        : (typeof platforms === 'string' && platforms.trim() ? [platforms] : [])
      const result = []
      const seen = new Set()
      source.forEach((platform) => {
        const normalized = this.normalizePlatform(platform)
        if (!normalized || seen.has(normalized)) return
        seen.add(normalized)
        result.push(normalized)
      })
      return result.length ? result : ['*']
    },

    doesPlatformMatch(item, platform) {
      const target = this.normalizePlatform(platform)
      const platforms = this.normalizePlatforms(item?.platforms || item?.package_platforms || item?.platform)
      if (!target || !platforms.length) return false
      if (platforms.includes('*')) return true
      return platforms.includes(target)
    },

    doesArchMatch(item, arch) {
      const target = this.normalizeArch(arch)
      const archs = this.normalizeArchs(item?.archs || item?.package_archs || item?.arch)
      if (!target || !archs.length) return false
      if (archs.includes('*')) return true
      return archs.includes(target)
    },

    doesPackageCompatibleTargetMatch(packageInfo, platform, arch) {
      const targetPlatform = this.normalizePlatform(platform)
      const targetArch = this.normalizeArch(arch)
      if (!targetPlatform || !targetArch) return false

      const compatibleTargets = Array.isArray(packageInfo?.compatible_targets)
        ? packageInfo.compatible_targets
        : []

      return compatibleTargets.some((item) => {
        const itemPlatform = this.normalizePlatform(item?.platform || '')
        const itemArch = this.normalizeArch(item?.arch || '')
        return itemPlatform === targetPlatform && itemArch === targetArch
      })
    },

    doesPackageBuildMatch(item, platform, arch) {
      const packages = item?.platform_packages || item?.package_meta?.platform_packages || null
      if (!packages || typeof packages !== 'object') return false
      const platformValue = this.normalizePlatform(platform)
      const archValue = this.normalizeArch(arch)
      if (!platformValue || !archValue) return false
      const exactKey = `${platformValue}-${archValue}`
      if (packages[exactKey]) return true
      return Object.values(packages).some((info) => {
        const itemPlatform = this.normalizePlatform(info?.platform || '')
        const itemArch = this.normalizeArch(info?.arch || '')
        const platformOk = itemPlatform === '*' || itemPlatform === platformValue
        const archOk = itemArch === '*' || itemArch === archValue
        if (platformOk && archOk) return true
        return this.doesPackageCompatibleTargetMatch(info, platformValue, archValue)
      })
    },

    formatPlatforms(platforms) {
      const normalized = this.normalizePlatforms(platforms)
      if (!normalized.length || normalized.includes('*')) return 'All platforms'
      return normalized.map((platform) => {
        if (platform === 'mac') return 'macOS'
        if (platform === 'win') return 'Windows'
        if (platform === 'linux') return 'Linux'
        if (platform === 'ios') return 'iOS'
        return platform
      }).join(', ')
    },

    moduleSearchText(item) {
      const moduleText = this.getPackageModules(item).map(module => [module.id, module.module_id, module.name, module.display_name, module.description].join(' ')).join(' ')
      const execText = Object.keys(item?.execs || {}).join(' ')
      return [
        item.id,
        item.name,
        item.display_name,
        item.description,
        item.package?.filename,
        item.package?.executable_rel_path,
        moduleText,
        execText,
        (item.tags || []).join(' '),
      ].map(value => String(value || '').toLowerCase()).join(' ')
    },

    downloadTool(item) {
      const id = String(item?.id || '').trim()
      if (!id) return
      const platform = this.selectedTargetPlatform
      const arch = this.selectedTargetArch

      this.logExternalToolTarget('download-package', item, {
        request_platform: platform,
        request_arch: arch,
      })

      if (!platform || !arch) {
        ElMessage.warning('Please select a valid target first')
        return
      }

      const downloadUrl = externalToolsApi.buildExternalToolDownloadUrl(id, { platform, arch })
      window.open(downloadUrl, '_blank')
    },

    getInstallMenuLabel(item = null) {
      const status = item ? this.getPackageCurrentInstallStatus(item) : null
      return status?.installed ? 'Installed on This Client' : 'Install on This Client'
    },

    getUninstallMenuLabel() {
      return 'Uninstall from This Client'
    },

    handlePackageMoreCommand(command, item) {
  if (command === 'download') return this.downloadTool(item)
  if (command === 'edit') return this.$emit('open-tool-meta-editor', item.id)
  if (!this.canUsePackageAction(item)) return null
  if (command === 'status') return this.showInstallStatus(item)
  if (command === 'copy') return this.copyInstallCommand(item)
  if (command === 'clear_cache') return this.clearPackageCache(item)
  if (command === 'uninstall') return this.uninstallPackage(item)
  return null
},

    getPackageTargetMachineId(item) {
      if (!item) return ''
      return this.selectedTargetMachineId
    },

    getPackageTargetConnectionIds(item) {
  if (!item) return []
  const machineId = this.getPackageTargetMachineId(item)
  const ids = this.getClientDeviceIdsForFilter(machineId)
  if (!ids.length) {
    this.logExternalToolTarget('package-target-connections-empty', item, {
      reason: 'selected machine has no matching client connections',
      selected_machine_id: machineId,
    })
  }
  return ids
},

    getPackageTargetInstanceRows(item, machineId = this.getPackageTargetMachineId(item)) {
  if (!item?.id) return []
  const packageId = String(item.id || '').trim()
  return this.allInstances.filter(row => (
    (row.package_id === packageId || String(row.tool_id || '').startsWith(`${packageId}.`)) &&
    row.machine_id === machineId
  ))
},

    hasRunningInstancesForPackage(item, machineId = this.getPackageTargetMachineId(item)) {
  return this.getPackageTargetInstanceRows(item, machineId).some(row => row.running || String(row.status || '').toLowerCase() === 'running')
},

    canUninstallPackageAction(item) {
  if (!this.canUsePackageAction(item)) return false
  const status = this.installStatuses[this.installStatusKey(item, this.getModuleInstallDeviceId(item))]
  if (status && status.installed === false) return false
  return !this.hasRunningInstancesForPackage(item)
},

    async uninstallPackage(item) {
  if (!item?.id) return
  if (!this.canUsePackageAction(item)) {
    ElMessage.warning('Please select a supported client first')
    return
  }

  const machineId = this.getPackageTargetMachineId(item)
  const deviceId = this.normalizeDeviceId(this.getPackageTargetConnectionIds(item)[0])
  if (!deviceId) return

  // 卸载前刷新一次实例状态，避免 UI 旧数据导致误删。
  try {
    await this.loadAllClientInstances(deviceId, false)
  } catch (_) {
    // refresh 失败不直接中断，后端/client 仍会再做一次 running 校验。
  }

  if (this.hasRunningInstancesForPackage(item, machineId)) {
    ElMessage.warning('This package still has running instances on this machine. Stop them before uninstalling.')
    return
  }

  try {
    await ElMessageBox.confirm(
      `Uninstall ${item.display_name || item.id} from this machine?`,
      'Uninstall External Tool',
      { type: 'warning', confirmButtonText: 'Uninstall', cancelButtonText: 'Cancel' },
    )
  } catch (_) {
    return
  }

  try {
    this.installLoading = true
    // 实际卸载只对当前选中的连接发命令；同 machine 多连接时，后端命令仍落在该机器本地路径。
    this.logExternalToolTarget('uninstall-client-package', item, {
      request_client_id: deviceId,
      request_platform: this.getPlatformForConnectionId(deviceId),
      request_arch: this.getArchForConnectionId(deviceId),
    })
    await this.uninstallClientTool(item, deviceId)
    await this.loadClientCatalogStatuses(deviceId, false)
    ElMessage.success(`Uninstalled: ${item.display_name || item.id}`)
  } catch (e) {
    ElMessage.error(e.message || 'Failed to uninstall package')
  } finally {
    this.installLoading = false
  }
},

    async uninstallClientTool(item, deviceId) {
  const targetDeviceId = this.normalizeDeviceId(deviceId)
  if (!targetDeviceId) throw new Error('Please select a device')

  const requestPlatform = this.getPlatformForConnectionId(targetDeviceId)
  const requestArch = this.getArchForConnectionId(targetDeviceId)
  this.logExternalToolTarget('uninstall-client-request', item, {
    request_client_id: targetDeviceId,
    request_platform: requestPlatform,
    request_arch: requestArch,
  })
  if (!requestPlatform || !requestArch) throw new Error(`Unable to resolve target platform/arch for client ${targetDeviceId}`)

  return externalToolsApi.uninstallClientTool(
    targetDeviceId,
    item.id,
    {
      params: {},
      platform: requestPlatform,
      arch: requestArch,
    },
    this.buildJsonHeaders(),
  )
},

    async clearPackageCache(item) {
      if (!item?.id) return
      if (!this.canUsePackageAction(item)) {
        ElMessage.warning('Please select a supported client first')
        return
      }
      const deviceId = this.getActionDeviceId(item)
      if (!deviceId) return
      try {
        await ElMessageBox.confirm(
          `Clear cached package archive for ${item.display_name || item.id} on this machine? Installed files will not be removed.`,
          'Clear Package Cache',
          { type: 'warning', confirmButtonText: 'Clear Cache', cancelButtonText: 'Cancel' },
        )
      } catch (_) {
        return
      }
      try {
        this.installLoading = true
        if (!deviceId) throw new Error('Please select a device')
        await this.clearClientPackageCache(item, deviceId)
        await this.loadClientCatalogStatuses(deviceId, false)
        ElMessage.success('Package cache cleared')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to clear package cache')
      } finally {
        this.installLoading = false
      }
    },

    async clearClientPackageCache(item, deviceId) {
      const targetDeviceId = this.normalizeDeviceId(deviceId)
      if (!targetDeviceId) throw new Error('Please select a device')

      const requestPlatform = this.getPlatformForConnectionId(targetDeviceId)
      const requestArch = this.getArchForConnectionId(targetDeviceId)
      this.logExternalToolTarget('clear-client-cache-request', item, {
        request_client_id: targetDeviceId,
        request_platform: requestPlatform,
        request_arch: requestArch,
      })
      if (!requestPlatform || !requestArch) throw new Error(`Unable to resolve target platform/arch for client ${targetDeviceId}`)

      return externalToolsApi.clearClientPackageCache(
        targetDeviceId,
        item.id,
        {
          params: {},
          platform: requestPlatform,
          arch: requestArch,
        },
        this.buildJsonHeaders(),
      )
    },

    async installOnly(item) {
      if (!this.canUsePackageAction(item)) {
        ElMessage.warning('Please select a supported client first')
        return
      }
      try {
        this.installLoading = true
        const deviceId = this.getActionDeviceId(item)
        if (!deviceId) throw new Error('Please select a target machine')
        const requestPlatform = this.getPlatformForConnectionId(deviceId)
        const requestArch = this.getArchForConnectionId(deviceId)
        this.logExternalToolTarget('install-client-package', item, {
          request_client_id: deviceId,
          request_platform: requestPlatform,
          request_arch: requestArch,
        })
        if (!requestPlatform || !requestArch) throw new Error(`Unable to resolve target platform/arch for client ${deviceId}`)

        await externalToolsApi.installClientTool(
          deviceId,
          item.id,
          { params: {}, platform: requestPlatform, arch: requestArch },
          this.buildJsonHeaders(),
        )
        await this.loadClientCatalogStatuses(deviceId, false)
        ElMessage.success('Installed successfully')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to install package')
      } finally {
        this.installLoading = false
      }
    },

    formatBytes(value) {
      return formatBytesHuman(value, { precision: 'one', maxUnit: 'GB', invalid: '0 B', nonPositiveAsZero: true })
    },

    formatExecMap(value) {
      const map = value && typeof value === 'object' ? value : {}
      const entries = Object.entries(map).filter(([name, path]) => String(name || '').trim() && String(path || '').trim())
      if (!entries.length) return '-'
      return entries.map(([name, path]) => `${name}: ${path}`).join('\n')
    },

    formatCommandMap(data) {
      const commands = data?.commands && typeof data.commands === 'object' ? data.commands : {}
      const entries = Object.entries(commands).filter(([name, command]) => String(name || '').trim() && String(command || '').trim())
      if (entries.length) return entries.map(([name, command]) => `${name}: ${command}`).join('\n')
      if (data?.command) return String(data.command)
      if (data?.executable_path) return String(data.executable_path)
      return '-'
    },

    packageExecNames(item) {
      return Object.keys(item?.execs || {}).filter(Boolean).join(', ') || '-'
    },

    formatInstallStatusDetails(data, item = null) {
      if (!data) return 'No install status available'
      const cache = data.cache || {}
      const newline = String.fromCharCode(10)
      const installLog = data.install_log || 'No install log available.'
      return [
        `Status: ${data.installed ? 'installed' : 'not installed'}`,
        `Install dir: ${data.install_dir || '-'}`,
        `Exec paths:${newline}${this.formatExecMap(data.exec_paths)}`,
        `Cached package: ${cache.exists || cache.cached ? 'yes' : 'no'}`,
        `Cache path: ${cache.cache_path || data.cache_path || '-'}`,
        `Cache size: ${cache.size ? this.formatBytes(cache.size) : '-'}`,
        `Cache mtime: ${cache.mtime || '-'}`,
        item?.source ? `Source: ${item.source}` : '',
        `Install log:${newline}${installLog}`,
      ].filter(Boolean).join(newline)
    },

    async getInstallStatusForAction(item) {
      const deviceId = this.getActionDeviceId(item)
      return this.fetchInstallStatus(item, deviceId, { silent: false, force: true })
    },

    async showInstallStatus(item) {
      const data = await this.getInstallStatusForAction(item)
      if (!data) return
      const modulesText = this.formatPackageModules(item) || '-'
      const execsText = this.packageExecNames(item)
      this.showDetailDialog({
        title: `${item.display_name || item.id} install status`,
        subtitle: `${item.id} / ${this.activeDeviceFilterLabel}`,
        copyText: this.formatCommandMap(data),
        sections: [
          {
            title: 'Package',
            rows: [
              { label: 'ID', value: item.id || '-', mono: true },
              { label: 'Modules', value: modulesText, mono: true, multiline: modulesText.includes('\n') },
              { label: 'Execs', value: execsText, mono: true },
              { label: 'Platform package', value: data.package_key || '-', mono: true },
              { label: 'Source', value: item.source || data.source || data.package_source || '-' },
            ],
          },
          {
            title: 'Install status',
            rows: [
              { label: 'Status', value: data.installed ? 'Installed' : (data.installed === false ? 'Not installed' : 'Unknown') },
              { label: 'Install dir', value: data.install_dir || '-', mono: true },
              { label: 'Exec paths', value: this.formatExecMap(data.exec_paths), mono: true, multiline: true },
            ],
          },
          {
            title: 'Package cache',
            rows: [
              { label: 'Cached package', value: (data.cache?.exists || data.cache?.cached || data.cached) ? 'Yes' : 'No' },
              { label: 'Cache path', value: data.cache?.cache_path || data.cache_path || '-', mono: true },
              { label: 'Cache dir', value: data.cache?.cache_dir || '-', mono: true },
              { label: 'Cache size', value: data.cache?.size ? this.formatBytes(data.cache.size) : '-' },
              { label: 'Cache mtime', value: data.cache?.mtime || '-' },
            ],
          },
          {
            title: 'Install log',
            rows: [
              { label: 'Path', value: data.install_log_path || '-', mono: true },
              { label: 'Log', value: data.install_log || 'No install log available.', mono: true, multiline: true },
            ],
          },
        ],
      })
    },

    async copyInstallCommand(item) {
      const data = await this.getInstallStatusForAction(item)
      if (!data) return
      const command = this.formatCommandMap(data)
      if (!command || command === '-') {
        ElMessage.warning('No command available to copy')
        return
      }
      try {
        if (window.isSecureContext && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
          await navigator.clipboard.writeText(command)
        } else {
          copyTextFallback(command)
        }
        ElMessage.success(data.installed ? 'Command copied' : 'Command copied; package is not installed yet')
      } catch (e) {
        try {
          copyTextFallback(command)
          ElMessage.success(data.installed ? 'Command copied' : 'Command copied; package is not installed yet')
        } catch (_) {
          ElMessage.error('Failed to copy command')
        }
      }
    },

    selectPackage(item) {
      if (!item?.id) return
      this.selectedPackageId = item.id
    },

    formatVersionLabel(version) {
  const value = String(version || '').trim()
  if (!value) return ''

  // 已经带 v 的标准数字版本，直接返回，避免 vv1.2.3
  if (/^v\d+\.\d+(?:\.\d+)?$/i.test(value)) {
    return value
  }

  // 只有 x.x 或 x.x.x 这种纯数字版本才自动加 v
  if (/^\d+\.\d+(?:\.\d+)?$/.test(value)) {
    return `v${value}`
  }

  // snapshot、commit、custom tag 等原样显示
  return value
},
  },
}
