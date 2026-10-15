import { h } from 'vue'
import { ElInput, ElMessage, ElMessageBox } from 'element-plus'
import { getConnectionRevisionStatus, listConnections, updateConnectionDeviceViewPrefs, verifyHiddenDevicesPassword } from '../api/connectionsApi.js'
import { assignMachineDeviceGroup, listDeviceGroups } from '../api/deviceGroupsApi.js'

const LAST_SELECTED_MACHINE_STORAGE_KEY = 'rch:last_selected_machine_id'
const LAST_SELECTED_CLIENT_STORAGE_KEY = 'rch:last_selected_client_id'

function emptyDeviceViewPrefs() {
    return {
        machineAliases: {},
        hiddenClientIds: {},
        hiddenMachineIds: {},
    }
}

function hasOwn(obj, key) {
    return Object.prototype.hasOwnProperty.call(obj || {}, key)
}

export default {
    data() {
        return {
            connections: [],
            selectedId: '',
            showHiddenDevices: false,
            deviceGroups: [],
            machineGroupAssignments: {},
            selectedDeviceGroupId: '',
            deviceViewPrefs: emptyDeviceViewPrefs(),
            locallyRemovedConnections: {
                clientIds: {},
                offlineMachineIds: {},
            },
            clientRevisionCheckSerial: {},
        }
    },

    methods: {
        buildConnectionIdentityKey(item) {
            if (!item) return ''
            return item.client_id
        },

        normalizeClientId(value) {
            return String(value || '').trim()
        },

        normalizeMachineId(value) {
            return String(value || '').trim()
        },

        getConnectionClientId(item) {
            return this.normalizeClientId(item?.client_id)
        },

        getConnectionMachineId(item) {
            return this.normalizeMachineId(item?.machine_id)
        },

        getStoredSelectedMachineId() {
            try {
                return this.normalizeMachineId(window.sessionStorage.getItem(LAST_SELECTED_MACHINE_STORAGE_KEY))
            } catch (e) {
                return ''
            }
        },

        getStoredSelectedClientId() {
            try {
                return this.normalizeClientId(window.sessionStorage.getItem(LAST_SELECTED_CLIENT_STORAGE_KEY))
            } catch (e) {
                return ''
            }
        },

        rememberSelectedConnection(item) {
            const machineId = this.getConnectionMachineId(item)
            const clientId = this.getConnectionClientId(item)
            try {
                if (machineId) {
                    window.sessionStorage.setItem(LAST_SELECTED_MACHINE_STORAGE_KEY, machineId)
                } else {
                    window.sessionStorage.removeItem(LAST_SELECTED_MACHINE_STORAGE_KEY)
                }
                if (clientId) {
                    window.sessionStorage.setItem(LAST_SELECTED_CLIENT_STORAGE_KEY, clientId)
                } else {
                    window.sessionStorage.removeItem(LAST_SELECTED_CLIENT_STORAGE_KEY)
                }
            } catch (e) {
                // sessionStorage 不可用时只影响刷新后的恢复，不影响当前连接选择。
            }
        },

        findPreferredConnectionForMachine(machineId, items = null) {
            const normalizedMachineId = this.normalizeMachineId(machineId)
            if (!normalizedMachineId) return null

            const candidates = Array.isArray(items) ? items : this.deviceSidebarConnections
            return candidates.find(item => {
                return this.getConnectionMachineId(item) === normalizedMachineId
            }) || null
        },

        normalizeDeviceGroupId(value) {
            return String(value || '').trim()
        },

        normalizeMachineGroupKey(value) {
            return this.normalizeMachineId(value).toLowerCase()
        },

        applyDeviceGroupState(payload = {}) {
            const groups = Array.isArray(payload?.groups)
                ? payload.groups
                    .map(item => ({
                        group_id: this.normalizeDeviceGroupId(item?.group_id || item?.id),
                        name: String(item?.name || '').trim(),
                        created_at: String(item?.created_at || ''),
                        updated_at: String(item?.updated_at || ''),
                    }))
                    .filter(item => item.group_id && item.name)
                : []

            const validGroupIds = new Set(groups.map(item => item.group_id))
            const assignments = {}
            const rawAssignments = payload?.machine_groups

            if (rawAssignments && typeof rawAssignments === 'object' && !Array.isArray(rawAssignments)) {
                Object.entries(rawAssignments).forEach(([machineId, groupId]) => {
                    const machineKey = this.normalizeMachineGroupKey(machineId)
                    const normalizedGroupId = this.normalizeDeviceGroupId(groupId)
                    if (machineKey && validGroupIds.has(normalizedGroupId)) {
                        assignments[machineKey] = normalizedGroupId
                    }
                })
            }

            this.deviceGroups = groups
            this.machineGroupAssignments = assignments

            if (this.selectedDeviceGroupId && !validGroupIds.has(this.selectedDeviceGroupId)) {
                this.selectedDeviceGroupId = ''
            }

            this.ensureSelectedConnectionVisible()
        },

        async loadDeviceGroups() {
            try {
                const payload = await listDeviceGroups()
                this.applyDeviceGroupState(payload)
            } catch (e) {
                ElMessage.error(e.message || 'Failed to load device groups')
            }
        },

        getMachineDeviceGroupId(machineId) {
            const machineKey = this.normalizeMachineGroupKey(machineId)
            if (!machineKey) return ''
            return this.normalizeDeviceGroupId(this.machineGroupAssignments?.[machineKey])
        },

        isConnectionInSelectedDeviceGroup(item) {
            const selectedGroupId = this.normalizeDeviceGroupId(this.selectedDeviceGroupId)
            if (!selectedGroupId) return true
            return this.getMachineDeviceGroupId(item?.machine_id) === selectedGroupId
        },

        setSelectedDeviceGroup(groupId) {
            const normalizedGroupId = this.normalizeDeviceGroupId(groupId)
            const exists = !normalizedGroupId || (this.deviceGroups || []).some(item => item.group_id === normalizedGroupId)
            this.selectedDeviceGroupId = exists ? normalizedGroupId : ''
            this.ensureSelectedConnectionVisible()
        },

        handleDeviceGroupsChanged(payload = {}) {
            this.applyDeviceGroupState(payload)
        },

        async assignMachineGroupFromSidebar(item, groupId = '') {
            const machineId = this.getConnectionMachineId(item)
            if (!machineId) {
                ElMessage.warning('Invalid machine id')
                return
            }

            try {
                const payload = await assignMachineDeviceGroup(
                    machineId,
                    this.normalizeDeviceGroupId(groupId),
                )
                this.applyDeviceGroupState(payload)

                const assignedGroup = (this.deviceGroups || []).find(group => {
                    return group.group_id === this.getMachineDeviceGroupId(machineId)
                })
                ElMessage.success(assignedGroup ? `Moved machine to ${assignedGroup.name}` : 'Machine group cleared')
            } catch (e) {
                ElMessage.error(e.message || 'Failed to update machine group')
            }
        },

        markConnectionLocallyRemoved(payload = {}) {
            const clientId = this.normalizeClientId(payload.client_id || payload.clientId)
            const machineId = this.normalizeMachineId(payload.machine_id || payload.machineId)

            const clientIds = { ...(this.locallyRemovedConnections?.clientIds || {}) }
            const offlineMachineIds = { ...(this.locallyRemovedConnections?.offlineMachineIds || {}) }

            if (clientId) clientIds[clientId] = true
            if (machineId) offlineMachineIds[machineId] = true

            this.locallyRemovedConnections = {
                clientIds,
                offlineMachineIds,
            }
        },

        clearConnectionLocallyRemoved(payload = {}) {
            const clientId = this.normalizeClientId(payload.client_id || payload.clientId)
            const machineId = this.normalizeMachineId(payload.machine_id || payload.machineId)

            const clientIds = { ...(this.locallyRemovedConnections?.clientIds || {}) }
            const offlineMachineIds = { ...(this.locallyRemovedConnections?.offlineMachineIds || {}) }

            if (clientId) delete clientIds[clientId]
            if (machineId) delete offlineMachineIds[machineId]

            this.locallyRemovedConnections = {
                clientIds,
                offlineMachineIds,
            }
        },

        isConnectionLocallyRemoved(item) {
            if (!item) return false

            const clientId = this.getConnectionClientId(item)
            if (clientId && this.locallyRemovedConnections?.clientIds?.[clientId]) {
                return true
            }

            const machineId = this.getConnectionMachineId(item)
            if (
                machineId &&
                this.locallyRemovedConnections?.offlineMachineIds?.[machineId] &&
                this.getConnectionDisplayState(item) === 'offline'
            ) {
                return true
            }

            return false
        },

        filterLocallyRemovedConnections(items) {
            return (Array.isArray(items) ? items : []).filter(item => !this.isConnectionLocallyRemoved(item))
        },

        getMachineAlias(machineId) {
            const id = this.normalizeMachineId(machineId)
            if (!id) return ''
            return String(this.deviceViewPrefs?.machineAliases?.[id] || '').trim()
        },

        isClientIdHidden(clientId) {
            const id = this.normalizeClientId(clientId)
            return Boolean(id && this.deviceViewPrefs?.hiddenClientIds?.[id])
        },

        isMachineIdHidden(machineId) {
            const id = this.normalizeMachineId(machineId)
            return Boolean(id && this.deviceViewPrefs?.hiddenMachineIds?.[id])
        },

        isConnectionHiddenByPrefs(item) {
            if (!item) return false
            return this.isClientIdHidden(item.client_id) || this.isMachineIdHidden(item.machine_id)
        },

        getDeviceDisplayName(item) {
            const alias = this.getMachineAlias(item?.machine_id)
            if (alias) return alias
            return String(item?.hostname || '').trim() || 'Unknown Host'
        },

        applyDeviceViewPrefsFromServer(item) {
            if (!item) return

            const clientId = this.getConnectionClientId(item)
            const machineId = this.getConnectionMachineId(item)
            const patch = {}

            if (machineId && (hasOwn(item, 'machine_alias') || hasOwn(item, 'device_alias'))) {
                const machineAliases = { ...(this.deviceViewPrefs.machineAliases || {}) }
                const alias = String(hasOwn(item, 'machine_alias') ? item.machine_alias : item.device_alias || '').trim()

                if (alias) {
                    machineAliases[machineId] = alias
                } else {
                    delete machineAliases[machineId]
                }

                patch.machineAliases = machineAliases
            }

            if (clientId && hasOwn(item, 'device_hidden_by_client')) {
                const hiddenClientIds = { ...(patch.hiddenClientIds || this.deviceViewPrefs.hiddenClientIds || {}) }
                if (item.device_hidden_by_client) {
                    hiddenClientIds[clientId] = true
                } else {
                    delete hiddenClientIds[clientId]
                }
                patch.hiddenClientIds = hiddenClientIds
            }

            if (machineId && hasOwn(item, 'device_hidden_by_machine')) {
                const hiddenMachineIds = { ...(patch.hiddenMachineIds || this.deviceViewPrefs.hiddenMachineIds || {}) }
                if (item.device_hidden_by_machine) {
                    hiddenMachineIds[machineId] = true
                } else {
                    delete hiddenMachineIds[machineId]
                }
                patch.hiddenMachineIds = hiddenMachineIds
            }

            if (Object.keys(patch).length) {
                this.patchDeviceViewPrefs(patch)
            }
        },

        mergeDeviceViewPrefsFromConnections(items) {
            ;(Array.isArray(items) ? items : []).forEach(item => {
                this.applyDeviceViewPrefsFromServer(item)
            })
        },

        decorateConnectionForDeviceView(item) {
            const alias = this.getMachineAlias(item?.machine_id)
            const hiddenByClient = this.isClientIdHidden(item?.client_id)
            const hiddenByMachine = this.isMachineIdHidden(item?.machine_id)

            return {
                ...item,
                device_alias: alias,
                machine_alias: alias,
                device_display_name: alias || String(item?.hostname || '').trim() || 'Unknown Host',
                device_hidden: hiddenByClient || hiddenByMachine,
                device_hidden_by_client: hiddenByClient,
                device_hidden_by_machine: hiddenByMachine,
            }
        },

        patchDeviceViewPrefs(patch = {}) {
            this.deviceViewPrefs = {
                ...emptyDeviceViewPrefs(),
                ...this.deviceViewPrefs,
                ...patch,
            }
        },

        applyClientHiddenLocal(clientId, hidden) {
            const id = this.normalizeClientId(clientId)
            if (!id) return

            const hiddenClientIds = { ...(this.deviceViewPrefs.hiddenClientIds || {}) }
            if (hidden) {
                hiddenClientIds[id] = true
            } else {
                delete hiddenClientIds[id]
            }

            this.patchDeviceViewPrefs({ hiddenClientIds })
        },

        applyMachineHiddenLocal(machineId, hidden) {
            const id = this.normalizeMachineId(machineId)
            if (!id) return

            const hiddenMachineIds = { ...(this.deviceViewPrefs.hiddenMachineIds || {}) }
            if (hidden) {
                hiddenMachineIds[id] = true
            } else {
                delete hiddenMachineIds[id]
            }

            this.patchDeviceViewPrefs({ hiddenMachineIds })
        },

        applyMachineAliasLocal(machineId, alias) {
            const id = this.normalizeMachineId(machineId)
            if (!id) return

            const machineAliases = { ...(this.deviceViewPrefs.machineAliases || {}) }
            const value = String(alias || '').trim()

            if (value) {
                machineAliases[id] = value
            } else {
                delete machineAliases[id]
            }

            this.patchDeviceViewPrefs({ machineAliases })
        },

        applyServerDeviceViewPrefsResponse(clientId, machineId, prefs = {}) {
            this.applyDeviceViewPrefsFromServer({
                client_id: clientId,
                machine_id: machineId,
                ...prefs,
            })
        },

        async setClientHidden(clientId, machineId, hidden) {
            const id = this.normalizeClientId(clientId)
            const machine = this.normalizeMachineId(machineId)
            if (!id) return

            const previousPrefs = { ...this.deviceViewPrefs, hiddenClientIds: { ...(this.deviceViewPrefs.hiddenClientIds || {}) } }
            this.applyClientHiddenLocal(id, hidden)

            try {
                const prefs = await updateConnectionDeviceViewPrefs({
                    client_id: id,
                    machine_id: machine,
                    client_hidden: !!hidden,
                })
                this.applyServerDeviceViewPrefsResponse(id, machine, prefs)
            } catch (e) {
                this.deviceViewPrefs = previousPrefs
                throw e
            }
        },

        async setMachineHidden(machineId, clientId, hidden) {
            const id = this.normalizeMachineId(machineId)
            const client = this.normalizeClientId(clientId)
            if (!id) return

            const previousPrefs = { ...this.deviceViewPrefs, hiddenMachineIds: { ...(this.deviceViewPrefs.hiddenMachineIds || {}) } }
            this.applyMachineHiddenLocal(id, hidden)

            try {
                const prefs = await updateConnectionDeviceViewPrefs({
                    client_id: client,
                    machine_id: id,
                    machine_hidden: !!hidden,
                })
                this.applyServerDeviceViewPrefsResponse(client, id, prefs)
            } catch (e) {
                this.deviceViewPrefs = previousPrefs
                throw e
            }
        },

        async setMachineAlias(machineId, clientId, alias) {
            const id = this.normalizeMachineId(machineId)
            const client = this.normalizeClientId(clientId)
            if (!id) return

            const previousPrefs = { ...this.deviceViewPrefs, machineAliases: { ...(this.deviceViewPrefs.machineAliases || {}) } }
            const value = String(alias || '').trim()
            this.applyMachineAliasLocal(id, value)

            try {
                const prefs = await updateConnectionDeviceViewPrefs({
                    client_id: client,
                    machine_id: id,
                    machine_alias: value,
                })
                this.applyServerDeviceViewPrefsResponse(client, id, prefs)
            } catch (e) {
                this.deviceViewPrefs = previousPrefs
                throw e
            }
        },

        // toggleShowHiddenDevices() {
        //     this.showHiddenDevices = !this.showHiddenDevices
        //     this.ensureSelectedConnectionVisible()
        // },

        async toggleShowHiddenDevices() {
    if (this.showHiddenDevices) {
        this.showHiddenDevices = false
        this.ensureSelectedConnectionVisible()
        return
    }

    try {
        // 先询问服务端是否启用验证；关闭时保持原来的无缝 toggle 行为。
        let verification = await verifyHiddenDevicesPassword()
        if (verification?.required) {
            let password = ''

            // 不使用 ElMessageBox.prompt 的裸 password input。
            // 独立 form + 明确的 autocomplete 语义，避免浏览器把页面里的 Command Input 误判成 username。
const passwordInput = h({
    name: 'HiddenDevicesPasswordInput',
    data() {
        return { value: '' }
    },
    render() {
        return h(ElInput, {
            type: 'password',
            name: 'rch-hidden-devices-password',
            autocomplete: 'new-password',
            placeholder: 'Password',
            modelValue: this.value,
            'onUpdate:modelValue': value => {
                this.value = String(value || '')
                password = this.value
            },
        })
    },
})

            const credentialForm = h(
                'form',
                {
                    autocomplete: 'off',
                    onSubmit: event => event.preventDefault(),
                },
                [
                    h('p', { style: 'margin:0 0 18px;' }, 'Enter the password to show hidden devices.'),
                    h('input', {
                        type: 'text',
                        name: 'rch-hidden-devices-username',
                        autocomplete: 'username',
                        tabindex: '-1',
                        'aria-hidden': 'true',
                        style: 'position:absolute;left:-10000px;width:1px;height:1px;opacity:0;pointer-events:none;',
                    }),
                    passwordInput,
                ],
            )

            const passwordDialog = ElMessageBox({
                title: 'Show Hidden Devices',
                message: credentialForm,
                customClass: 'hidden-devices-password-message-box',
                showCancelButton: true,
                confirmButtonText: 'Show',
                cancelButtonText: 'Cancel',
                autofocus: false,
                beforeClose: (action, _instance, done) => {
                    if (action === 'confirm' && !password) {
                        ElMessage.warning('Password is required')
                        return
                    }
                    done()
                },
            })

            // MessageBox 的 FocusTrap 会在打开时设置一次初始焦点；
            // 等它完成后，再聚焦密码框里的真实 input。
            setTimeout(() => {
                const input = document.querySelector(
                    '.hidden-devices-password-message-box input[name="rch-hidden-devices-password"]',
                )
                input?.focus({ preventScroll: true })
            }, 0)

            await passwordDialog

            verification = await verifyHiddenDevicesPassword(password)
            if (!verification?.verified) {
                ElMessage.error('Invalid password')
                return
            }
        }

        this.showHiddenDevices = true
        this.ensureSelectedConnectionVisible()
    } catch (e) {
        if (e === 'cancel' || e === 'close' || e?.toString?.().includes('cancel')) return
        ElMessage.error(e.message || 'Failed to verify hidden devices password')
    }
},

        ensureSelectedConnectionVisible() {
            const sidebarConnections = Array.isArray(this.deviceSidebarConnections)
                ? this.deviceSidebarConnections
                : []
            const selected = this.connections.find(item => item.client_id === this.selectedId)
            const selectedVisible = sidebarConnections.find(item => item.client_id === this.selectedId)

            if (selectedVisible) {
                this.rememberSelectedConnection(selectedVisible)
                return
            }

            const preferredMachineId = this.getConnectionMachineId(selected) || this.getStoredSelectedMachineId()
            const storedClientId = this.getStoredSelectedClientId()
            const exactMatch = storedClientId ? sidebarConnections.find(item => (
                this.getConnectionClientId(item) === storedClientId
                && (!preferredMachineId || this.getConnectionMachineId(item) === preferredMachineId)
            )) : null
            const next = exactMatch || this.findPreferredConnectionForMachine(preferredMachineId, sidebarConnections)
            const previousSelectedId = this.selectedId
            this.selectedId = next?.client_id || ''

            if (next && next.client_id !== previousSelectedId) {
                this.rememberSelectedConnection(next)
                this.ensureOutputBucket?.(next.client_id)
                this.refreshClientRevisionStatus(next)
            }
        },

        async renameMachineFromSidebar(item) {
            const machineId = this.getConnectionMachineId(item)
            if (!machineId) {
                ElMessage.warning('Invalid machine id')
                return
            }

            const currentAlias = this.getMachineAlias(machineId)
            const hostname = String(item?.hostname || '').trim()
            const title = currentAlias ? 'Edit Machine Alias' : 'Set Machine Alias'

            try {
                const { value } = await ElMessageBox.prompt(
                    `Alias for ${hostname || machineId}. Leave empty to clear alias.`,
                    title,
                    {
                        confirmButtonText: 'Save',
                        cancelButtonText: 'Cancel',
                        inputValue: currentAlias,
                        inputPlaceholder: hostname || 'Machine alias',
                    },
                )

                await this.setMachineAlias(machineId, item?.client_id, value)
                ElMessage.success(String(value || '').trim() ? 'Alias saved' : 'Alias cleared')
            } catch (e) {
                if (e === 'cancel' || e === 'close' || e?.toString?.().includes('cancel')) return
                ElMessage.error(e.message || 'Failed to save alias')
            }
        },

        async toggleClientHiddenFromSidebar(item) {
            const clientId = this.getConnectionClientId(item)
            if (!clientId) {
                ElMessage.warning('Invalid client id')
                return
            }

            const nextHidden = !this.isClientIdHidden(clientId)
            try {
                await this.setClientHidden(clientId, item?.machine_id, nextHidden)
                this.ensureSelectedConnectionVisible()
                ElMessage.success(nextHidden ? 'Connection hidden' : 'Connection unhidden')
            } catch (e) {
                ElMessage.error(e.message || 'Failed to update connection hidden status')
            }
        },

        async toggleMachineHiddenFromSidebar(item) {
            const machineId = this.getConnectionMachineId(item)
            if (!machineId) {
                ElMessage.warning('Invalid machine id')
                return
            }

            const nextHidden = !this.isMachineIdHidden(machineId)
            try {
                await this.setMachineHidden(machineId, item?.client_id, nextHidden)
                this.ensureSelectedConnectionVisible()
                ElMessage.success(nextHidden ? 'Machine hidden' : 'Machine unhidden')
            } catch (e) {
                ElMessage.error(e.message || 'Failed to update machine hidden status')
            }
        },

        dedupeConnections(items) {
            const grouped = new Map()
            const ordered = []

            this.filterLocallyRemovedConnections(items).forEach((item) => {
                if (!item || !item.client_id) return

                const key = item.client_id
                const existing = grouped.get(key)

                if (!existing) {
                    const copy = { ...item }
                    grouped.set(key, copy)
                    ordered.push(copy)
                    return
                }

                const existingState = this.getConnectionDisplayState(existing)
                const currentState = this.getConnectionDisplayState(item)

                if (existingState === 'offline' && currentState !== 'offline') {
                    Object.assign(existing, item, { disconnected_at: '' })
                    return
                }

                if (existingState !== 'offline' && currentState === 'offline') {
                    return
                }

                const existingTime = this.getConnectionActivityTimeMs(existing)
                const currentTime = this.getConnectionActivityTimeMs(item)

                if (currentTime >= existingTime) {
                    Object.assign(existing, item)
                }
            })

            const activeItems = []
            const activeMachineIds = new Set()
            const latestOfflineByMachine = new Map()
            const offlineWithoutMachine = []

            ordered.forEach((item) => {
                const state = this.getConnectionDisplayState(item)
                const machineId = this.getConnectionMachineId(item)

                if (state !== 'offline') {
                    activeItems.push(item)
                    if (machineId) activeMachineIds.add(machineId)
                    return
                }

                if (!machineId) {
                    offlineWithoutMachine.push(item)
                    return
                }

                const existing = latestOfflineByMachine.get(machineId)
                if (!existing || this.getConnectionActivityTimeMs(item) >= this.getConnectionActivityTimeMs(existing)) {
                    latestOfflineByMachine.set(machineId, item)
                }
            })

            const offlineItems = offlineWithoutMachine.concat(
                Array.from(latestOfflineByMachine.entries())
                    .filter(([machineId]) => !activeMachineIds.has(machineId))
                    .map(([, item]) => item),
            )
            offlineItems.sort(this.compareConnectionActivityDesc)

            return activeItems.concat(offlineItems)
        },

        async loadConnections() {
            try {
                const fetchedConnections = this.filterLocallyRemovedConnections(await listConnections())
                this.mergeDeviceViewPrefsFromConnections(fetchedConnections)

                const existingMap = new Map()
                ;(this.connections || []).forEach(item => {
                    if (item && item.client_id) {
                        existingMap.set(item.client_id, { ...item })
                    }
                })

                const fetchedMap = new Map()
                const frontItems = []

                fetchedConnections.forEach(item => {
                    if (!item || !item.client_id) return

                    const existing = existingMap.get(item.client_id)
                    const existingState = this.getConnectionDisplayState(existing)
                    const incomingState = this.getConnectionDisplayState(item)
                    const merged = {
                        ...existing,
                        ...item,
                    }

                    if (incomingState !== 'offline') {
                        merged.disconnected_at = ''
                    }

                    fetchedMap.set(item.client_id, merged)

                    if (!existing || (existingState === 'offline' && incomingState !== 'offline')) {
                        frontItems.push(merged)
                    }
                })

                frontItems.sort(this.compareConnectionActivityDesc)

                const nextItems = []
                const usedIds = new Set()

                frontItems.forEach(item => {
                    if (!item || !item.client_id || usedIds.has(item.client_id)) return
                    nextItems.push(item)
                    usedIds.add(item.client_id)
                })

                ;(this.connections || []).forEach(oldItem => {
                    if (!oldItem || !oldItem.client_id || usedIds.has(oldItem.client_id)) return

                    const merged = fetchedMap.get(oldItem.client_id) || oldItem
                    nextItems.push(merged)
                    usedIds.add(oldItem.client_id)
                })

                fetchedConnections.forEach(item => {
                    if (!item || !item.client_id || usedIds.has(item.client_id)) return

                    const merged = fetchedMap.get(item.client_id) || item
                    nextItems.push(merged)
                    usedIds.add(item.client_id)
                })

                this.connections = this.dedupeConnections(nextItems)

                const selectedIdBeforeVisibilityCheck = this.selectedId
                this.ensureSelectedConnectionVisible()

                if (this.selectedId && this.selectedId === selectedIdBeforeVisibilityCheck) {
                    const selected = this.connections.find(item => item.client_id === this.selectedId)
                    if (!selected || this.getConnectionDisplayState(selected) !== 'online') {
                        this.clearClientRevisionNotice(this.selectedId)
                    } else if (String(selected.client_revision_state || '').trim() === 'current') {
                        this.clearClientRevisionNotice(this.selectedId)
                    } else if (!this.hasClientRevisionNotice(this.selectedId)) {
                        this.refreshClientRevisionStatus(selected)
                    }
                }

                if (this.selectedId) {
                    await this.reloadCommandCandidatesFromRuntime?.({
                        reset: true,
                        silent: true,
                    })
                }
            } catch (e) {
                ElMessage.error('Failed to load devices')
            }
        },

        upsertConnection(conn) {
            if (!conn || !conn.client_id) return

            this.applyDeviceViewPrefsFromServer(conn)

            if (this.isConnectionLocallyRemoved(conn)) {
                this.connections = this.filterLocallyRemovedConnections(this.connections)
                this.ensureSelectedConnectionVisible()
                return
            }

            const identityKey = this.buildConnectionIdentityKey(conn)
            const incomingState = this.getConnectionDisplayState(conn)

            const duplicateIndexes = []
            this.connections.forEach((item, index) => {
                if (!item) return

                const sameClientId = item.client_id === conn.client_id
                const sameIdentity = identityKey && this.buildConnectionIdentityKey(item) === identityKey

                if (sameClientId || sameIdentity) {
                    duplicateIndexes.push(index)
                }
            })

            if (!duplicateIndexes.length) {
                const nextItem = { ...conn }

                if (incomingState === 'offline') {
                    this.connections.push(nextItem)
                } else {
                    this.connections.unshift(nextItem)
                }

                this.connections = this.dedupeConnections(this.connections)
                this.ensureSelectedConnectionVisible()
                return
            }

            const primaryIndex = duplicateIndexes[0]
            const oldItem = this.connections[primaryIndex]
            const oldState = this.getConnectionDisplayState(oldItem)

            const merged = {
                ...oldItem,
                ...conn,
            }

            if (incomingState !== 'offline') {
                merged.disconnected_at = ''
            }

            if (incomingState === 'offline' && !merged.disconnected_at) {
                merged.disconnected_at = new Date().toISOString()
            }

            duplicateIndexes
                .slice()
                .sort((a, b) => b - a)
                .forEach(index => {
                    this.connections.splice(index, 1)
                })

            if (incomingState === 'offline') {
                this.connections.push(merged)
            } else if (oldState === 'offline') {
                this.connections.unshift(merged)
            } else {
                const removedBefore = duplicateIndexes.filter(index => index < primaryIndex).length
                const stableIndex = Math.max(primaryIndex - removedBefore, 0)
                this.connections.splice(stableIndex, 0, merged)
            }

            this.connections = this.dedupeConnections(this.connections)
            this.ensureSelectedConnectionVisible()
        },

        removeConnection(clientId) {
            const normalizedClientId = this.normalizeClientId(clientId)

            if (normalizedClientId && this.locallyRemovedConnections?.clientIds?.[normalizedClientId]) {
                this.connections = this.filterLocallyRemovedConnections(this.connections)
                this.ensureSelectedConnectionVisible()
                return
            }

            const idx = this.connections.findIndex(item => item.client_id === clientId)
            if (idx === -1) return

            const oldItem = this.connections[idx]
            const offlineItem = {
                ...oldItem,
                connection_state: 'offline',
                disconnected_at: oldItem.disconnected_at || new Date().toISOString(),
                is_transfer_active: false,
            }

            this.connections.splice(idx, 1)
            this.connections.push(offlineItem)
            this.connections = this.dedupeConnections(this.connections)
            this.ensureSelectedConnectionVisible()
        },

        forgetConnectionFromDeviceView(payload = {}) {
            const selectedBefore = this.selectedId

            this.markConnectionLocallyRemoved(payload)
            this.connections = this.filterLocallyRemovedConnections(this.connections)

            const selectedStillExists = this.connections.some(item => {
                return this.normalizeClientId(item?.client_id) === selectedBefore
            })

            if (!selectedStillExists) {
                this.selectedId = ''
            }

            this.ensureSelectedConnectionVisible()
        },

        async restoreConnectionFromDeviceView(payload = {}) {
            this.clearConnectionLocallyRemoved(payload)
            await this.loadConnections()
        },

        getConnectionActivityTimeMs(item) {
            if (!item) return Number.NEGATIVE_INFINITY

            const candidates = [
                item.disconnected_at,
                item.last_seen_at,
                item.connected_at,
            ]

            const validTimes = candidates
                .map(value => Date.parse(String(value || '').trim()))
                .filter(value => Number.isFinite(value))

            if (!validTimes.length) {
                return Number.NEGATIVE_INFINITY
            }

            return Math.max(...validTimes)
        },

        compareConnectionActivityDesc(a, b) {
            const ta = this.getConnectionActivityTimeMs(a)
            const tb = this.getConnectionActivityTimeMs(b)

            if (ta !== tb) {
                return tb > ta ? 1 : -1
            }

            const fa = String(a?.hostname || a?.machine_id || a?.client_id || '')
            const fb = String(b?.hostname || b?.machine_id || b?.client_id || '')
            return fa.localeCompare(fb)
        },

        clearClientRevisionNotice(clientId) {
            const normalizedClientId = this.normalizeClientId(clientId)
            if (!normalizedClientId) return

            this.ensureOutputBucket?.(normalizedClientId)
            const lines = Array.isArray(this.outputs?.[normalizedClientId]) ? this.outputs[normalizedClientId] : []
            this.outputs[normalizedClientId] = lines.filter(line => line?.meta?.clientRevisionNotice !== true)
        },

        hasClientRevisionNotice(clientId) {
            const normalizedClientId = this.normalizeClientId(clientId)
            if (!normalizedClientId) return false
            const lines = Array.isArray(this.outputs?.[normalizedClientId]) ? this.outputs[normalizedClientId] : []
            return lines.some(line => line?.meta?.clientRevisionNotice === true)
        },

        appendClientRevisionNotice(item, revisionStatus = null) {
            const clientId = this.getConnectionClientId(item)
            if (!clientId) return

            this.clearClientRevisionNotice(clientId)
            if (!item || this.getConnectionDisplayState(item) !== 'online') return

            const status = revisionStatus && typeof revisionStatus === 'object'
                ? revisionStatus
                : { state: item.client_revision_state || '' }
            const revisionState = String(status.state || '').trim()
            const commandManifest = Array.isArray(item.command_manifest) ? item.command_manifest : []
            const supportsUpdate = commandManifest.some(entry => String(entry?.name || '').trim() === 'update')
            const buildVersion = String(item.build_version || '').trim().toLowerCase()
            const isDevBuild = buildVersion === 'dev'
            let message = ''
            let suggestedCommand = ''

            if (revisionState === 'outdated') {
                if (isDevBuild) {
                    message = '[!] Client code is outdated. Restart from IDE/source.'
                } else {
                    message = '[!] Client code is outdated. Please run update.'
                    suggestedCommand = 'update'
                }
            } else if (revisionState === 'unknown' && supportsUpdate) {
                if (isDevBuild) {
                    message = '[!] Client revision is unavailable. Restart from IDE/source after code changes.'
                } else {
                    message = '[!] Client revision is unavailable. Please run update once.'
                    suggestedCommand = 'update'
                }
            }

            if (!message) return

            this.appendOutput?.(
                clientId,
                message,
                'warning',
                {
                    clientRevisionNotice: true,
                    ...(revisionState === 'outdated' ? {
                        clientRevisionDetails: {
                            current_revision: String(status.current_revision || item.client_revision || '').trim(),
                            server_revision: String(status.server_revision || '').trim(),
                            changed_files: Array.isArray(status.changed_files) ? status.changed_files : [],
                            changed_files_available: status.changed_files_available === true,
                        },
                    } : {}),
                    ...(suggestedCommand ? {
                        suggestedCommand,
                        suggestedCommandLabel: 'Update',
                    } : {}),
                },
            )
        },

        async refreshClientRevisionStatus(item) {
            const clientId = this.getConnectionClientId(item)
            if (!clientId) return

            if (!item || this.getConnectionDisplayState(item) !== 'online') {
                this.clearClientRevisionNotice(clientId)
                return
            }

            const serial = Number(this.clientRevisionCheckSerial?.[clientId] || 0) + 1
            this.clientRevisionCheckSerial = {
                ...(this.clientRevisionCheckSerial || {}),
                [clientId]: serial,
            }

            try {
                const status = await getConnectionRevisionStatus(clientId)
                if (Number(this.clientRevisionCheckSerial?.[clientId] || 0) !== serial) return

                const current = this.connections.find(entry => this.getConnectionClientId(entry) === clientId)
                if (!current || this.getConnectionDisplayState(current) !== 'online') {
                    this.clearClientRevisionNotice(clientId)
                    return
                }

                current.client_revision_state = String(status?.state || '')
                if (this.selectedId === clientId) {
                    this.appendClientRevisionNotice(current, status)
                }
            } catch (e) {
                if (Number(this.clientRevisionCheckSerial?.[clientId] || 0) !== serial) return
                this.clearClientRevisionNotice(clientId)
            }
        },

        // compareSidebarConnectionOrder(a, b) {
        //     const rawOrderA = a?.machine_order
        //     const rawOrderB = b?.machine_order
        //     const orderA = rawOrderA === null || rawOrderA === undefined || rawOrderA === '' ? NaN : Number(rawOrderA)
        //     const orderB = rawOrderB === null || rawOrderB === undefined || rawOrderB === '' ? NaN : Number(rawOrderB)
        //     const normalizedOrderA = Number.isFinite(orderA) ? orderA : Number.MAX_SAFE_INTEGER
        //     const normalizedOrderB = Number.isFinite(orderB) ? orderB : Number.MAX_SAFE_INTEGER
        //
        //     if (normalizedOrderA !== normalizedOrderB) {
        //         return normalizedOrderA - normalizedOrderB
        //     }
        //
        //     const machineA = this.getConnectionMachineId(a)
        //     const machineB = this.getConnectionMachineId(b)
        //     if (machineA !== machineB) {
        //         return machineA.localeCompare(machineB)
        //     }
        //
        //     const connectedA = Date.parse(String(a?.connected_at || '').trim())
        //     const connectedB = Date.parse(String(b?.connected_at || '').trim())
        //     const timeA = Number.isFinite(connectedA) ? connectedA : Number.NEGATIVE_INFINITY
        //     const timeB = Number.isFinite(connectedB) ? connectedB : Number.NEGATIVE_INFINITY
        //
        //     if (timeA !== timeB) {
        //         return timeB > timeA ? 1 : -1
        //     }
        //
        //     return this.getConnectionClientId(a).localeCompare(this.getConnectionClientId(b))
        // },


        compareSidebarConnectionOrder(a, b) {
    // online 固定在前，offline 固定在后，其他状态保持在中间。
    const stateRank = item => {
        const state = this.getConnectionDisplayState(item)
        if (state === 'online') return 0
        if (state === 'offline') return 2
        return 1
    }
    const stateRankA = stateRank(a)
    const stateRankB = stateRank(b)

    if (stateRankA !== stateRankB) {
        return stateRankA - stateRankB
    }

    const rawOrderA = a?.machine_order
    const rawOrderB = b?.machine_order
    const orderA = rawOrderA === null || rawOrderA === undefined || rawOrderA === '' ? NaN : Number(rawOrderA)
    const orderB = rawOrderB === null || rawOrderB === undefined || rawOrderB === '' ? NaN : Number(rawOrderB)
    const normalizedOrderA = Number.isFinite(orderA) ? orderA : Number.MAX_SAFE_INTEGER
    const normalizedOrderB = Number.isFinite(orderB) ? orderB : Number.MAX_SAFE_INTEGER

    if (normalizedOrderA !== normalizedOrderB) {
        return normalizedOrderA - normalizedOrderB
    }

    const machineA = this.getConnectionMachineId(a)
    const machineB = this.getConnectionMachineId(b)
    if (machineA !== machineB) {
        return machineA.localeCompare(machineB)
    }

    const connectedA = Date.parse(String(a?.connected_at || '').trim())
    const connectedB = Date.parse(String(b?.connected_at || '').trim())
    const timeA = Number.isFinite(connectedA) ? connectedA : Number.NEGATIVE_INFINITY
    const timeB = Number.isFinite(connectedB) ? connectedB : Number.NEGATIVE_INFINITY

    if (timeA !== timeB) {
        return timeB > timeA ? 1 : -1
    }

    return this.getConnectionClientId(a).localeCompare(this.getConnectionClientId(b))
},

        clearSelectedConnection() {
            this.selectedId = ''
            this.rememberSelectedConnection(null)
            this.commandHistoryItems = []
            this.commandExecutionItems = []
            this.reloadCommandCandidatesFromRuntime?.({
                reset: true,
                silent: true,
            })
        },

        selectConnection(clientId) {
            this.selectedId = clientId
            const selected = this.connections.find(item => item.client_id === clientId)
            this.rememberSelectedConnection(selected)
            this.ensureOutputBucket(clientId)
            this.refreshClientRevisionStatus(selected)
            this.commandHistoryItems = []
            this.commandExecutionItems = []
            this.reloadCommandCandidatesFromRuntime?.({
                reset: true,
                silent: true,
            })
            this.scrollToBottom()
            this.refreshBackgroundJobsIfOpen?.()
        },

        getConnectionDisplayState(conn) {
            const state = String(conn && conn.connection_state || '').trim()
            if (state === 'offline') return 'offline'

            if (conn && conn.is_transfer_active) {
                return 'online'
            }

            const disconnectedAt = String(conn && conn.disconnected_at || '').trim()
            if (disconnectedAt) return 'offline'

            const lastSeenAt = String(conn && conn.last_seen_at || '').trim()
            if (!lastSeenAt) return state || 'online'

            const staleAfterSeconds = Number(conn && conn.stale_after_seconds || 45)
            const seenMs = Date.parse(lastSeenAt)
            if (!Number.isFinite(seenMs)) return state || 'online'

            const ageMs = Math.max(this.statusNowTick - seenMs, 0)
            if (ageMs > staleAfterSeconds * 1000) return 'stale'

            return 'online'
        },
    },

    computed: {
        machineAliasMap() {
            return { ...(this.deviceViewPrefs?.machineAliases || {}) }
        },

        deviceSidebarConnections() {
            const decorated = (this.connections || []).map(item => this.decorateConnectionForDeviceView(item))
            const grouped = decorated.filter(item => this.isConnectionInSelectedDeviceGroup(item))
            const visible = this.showHiddenDevices
                ? grouped
                : grouped.filter(item => !item.device_hidden)
            return visible.slice().sort(this.compareSidebarConnectionOrder)
        },

        deviceGroupMachineCounts() {
            const allMachineKeys = new Set()
            const groupMachineKeys = {}

            ;(this.connections || []).forEach(item => {
                const machineKey = this.normalizeMachineGroupKey(item?.machine_id)
                const fallbackClientId = this.normalizeClientId(item?.client_id)
                const deviceKey = machineKey || (fallbackClientId ? `client:${fallbackClientId}` : '')
                if (!deviceKey) return

                allMachineKeys.add(deviceKey)

                if (!machineKey) return
                const groupId = this.getMachineDeviceGroupId(machineKey)
                if (!groupId) return

                if (!groupMachineKeys[groupId]) {
                    groupMachineKeys[groupId] = new Set()
                }
                groupMachineKeys[groupId].add(machineKey)
            })

            const counts = {
                __all__: allMachineKeys.size,
            }

            ;(this.deviceGroups || []).forEach(group => {
                const groupId = this.normalizeDeviceGroupId(group?.group_id)
                if (!groupId) return
                counts[groupId] = groupMachineKeys[groupId]?.size || 0
            })

            return counts
        },

        currentConnection() {
            return this.connections.find(item => item.client_id === this.selectedId) || null
        },

        onlineConnectionsCount() {
            return (this.deviceSidebarConnections || []).filter(item => this.getConnectionDisplayState(item) === 'online').length
        },
    },
}
