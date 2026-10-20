<template>
  <div class="command-row">
    <div class="command-box command-box-full">
      <div class="command-autocomplete-shell">
<el-autocomplete
  ref="commandInputRef"
  :model-value="commandText"
  :fetch-suggestions="queryCommandCandidates"
  :fit-input-width="true"
  popper-class="command-autocomplete-popper"
  :class="{ 'command-autocomplete-preview': autocompleteNavigationPreviewActive }"
  class="command-autocomplete"
  value-key="value"
  placeholder="Enter a command."
  @update:model-value="handleCommandTextUpdate"
  @select="handleCandidateSelect"
  @keydown.capture="handleCommandInputKeydown"
  @keyup.enter="sendCommand"
>
          <template #default="{ item }">
            <div
              class="command-autocomplete-item"
              @mouseenter="handleAutocompleteCandidateMouseEnter(item)"
            >
              <div class="command-autocomplete-item-main">
                <div
                  class="command-autocomplete-item-name"
                  :title="item.displayText || item.template || item.value || '-'"
                >
                  {{ item.displayText || item.template || item.value || '-' }}
                </div>

                <div
                  v-if="item.help"
                  class="command-autocomplete-item-desc"
                  :title="item.help"
                >
                  {{ item.help }}
                </div>
              </div>

              <div
                v-if="item.groupLabel"
                class="command-autocomplete-item-group"
              >
                {{ item.groupLabel }}
              </div>
            </div>
          </template>
        </el-autocomplete>
      </div>

      <button
        class="run-button"
        :disabled="sending || hasRunningWebTask"
        @click="sendCommand"
      >
        <span v-if="!sending && !hasRunningWebTask">Run</span>
        <span v-else-if="sending">...</span>
        <span v-else>Busy</span>
      </button>

      <el-button
        class="run-button cancel-button"
        :disabled="!hasRunningWebTask"
        :loading="cancelSending"
        @click="cancelCurrentTask"
      >
        Cancel
      </el-button>
    </div>
  </div>
</template>

<script>
import { ElMessage } from 'element-plus'
import {
  sendCommand as sendCommandApi,
  getCommandCandidates,
  getCommandHistory,
  getCommandCompletions,
} from '../api/connectionsApi.js'
import { cancelTask } from '../api/tasksApi.js'
import {
  formatTerminalCancelRequestedLine,
  formatTerminalCommandFailedLine,
} from '../composables/terminalMarkers.js'

const DIRECTORY_ONLY_COMPLETION_COMMANDS = [
  'cd',
  'rmdir',
]

const PATH_COMPLETION_COMMANDS = [
  'download',
  'cat',
  'file',
  'allow_file',
  'acmd image_info',
  'acmd sqlite_query',
  'python3'
]

export default {
  name: 'CommandInputBar',


  props: {
    selectedId: {
      type: [String, Number],
      default: '',
    },

    currentConnection: {
      type: Object,
      default: null,
    },

    currentActiveTaskId: {
      type: [String, Number],
      default: '',
    },

    tabId: {
      type: String,
      default: '',
    },
  },

  emits: [
    'append-output',
    'set-active-task',
    'clear-output',
  ],

  data() {
    return {
      commandText: '',
      sending: false,
      cancelSending: false,
      commandCandidates: [],
      commandCandidatesLoadedFor: '',
      commandCandidatesLoadPromise: null,
      commandCompletionCandidatesByContext: {},
      commandCompletionCandidatesLoadPromises: {},
      commandCompletionDebounceTimer: null,
      commandCompletionDebounceResolve: null,
      commandCompletionDebounceToken: 0,
      autocompleteCandidateItems: [],
      autocompleteCandidateQueryText: '',
      autocompleteNavigationBaseText: '',
      autocompleteNavigationIndex: -1,
      autocompleteNavigationPreviewActive: false,
    }
  },

  computed: {
    hasRunningWebTask() {
      return !!String(this.currentActiveTaskId || '').trim()
    },
  },

  watch: {
    selectedId: {
      immediate: true,
      handler(value, oldValue) {
        if (value !== oldValue) {
          this.cancelSending = false
          this.commandCandidates = []
          this.commandCandidatesLoadedFor = ''
          this.clearCommandCompletionCandidateCache()
        }

        if (value) {
          this.reloadCommandCandidates({ reset: true, silent: true })
        }
      },
    },

    currentActiveTaskId(value) {
      if (!value) {
        this.cancelSending = false
      }
    },

    'currentConnection.machine_id'(value, oldValue) {
      if (value !== oldValue && this.selectedId) {
        this.reloadCommandCandidates({ reset: true, silent: true })
      }
    },

    'currentConnection.cwd'(value, oldValue) {
      if (value !== oldValue) {
        this.clearCommandCompletionCandidateCache()
      }
    },
  },

  beforeUnmount() {
    this.clearCommandCompletionCandidateCache()
  },

  methods: {

    async sendCommand() {
  const command = String(this.commandText || '').trim()

  // add 暂时关闭命令自动补全下拉 2026-04-07
  this.closeAutocomplete()
  this.clearAutocompleteNavigationState()

  if (!command) {
    ElMessage.warning('Please enter a command')
    return
  }

  if (!this.selectedId) {
    ElMessage.warning('Please select a device')
    return
  }

  if (this.handleLocalFrontendCommand(command)) {
    return
  }

  this.sending = true
  this.$emit('append-output', this.selectedId, '> ' + command, 'command')

  try {
    const data = await sendCommandApi(this.selectedId, command, this.getTabScopedHeaders())
    const taskId = data && data.task_id
    this.$emit('set-active-task', this.selectedId, taskId || '')

    this.commandText = ''
    this.commandCandidatesLoadedFor = ''
    this.clearCommandCompletionCandidateCache()
    await this.loadCommandCandidates(this.selectedId)
  } catch (e) {
    this.$emit('append-output', this.selectedId, formatTerminalCommandFailedLine(e.message || 'unknown error'), 'error')
    ElMessage.error(e.message || 'Command failed')
    this.commandText = ''
  } finally {
    this.sending = false
  }
},

    // async sendCommand() {
    //   const command = String(this.commandText || '').trim()
    //
    //   // add 暂时关闭命令自动补全下拉 2026-04-07
    //   this.closeAutocomplete()
    //
    //   if (!this.selectedId) {
    //     ElMessage.warning('Please select a device')
    //     return
    //   }
    //
    //   if (!command) {
    //     ElMessage.warning('Please enter a command')
    //     return
    //   }
    //
    //   this.sending = true
    //   this.$emit('append-output', this.selectedId, '> ' + command, 'command')
    //
    //   try {
    //     const data = await sendCommandApi(this.selectedId, command, this.getTabScopedHeaders())
    //     const taskId = data && data.task_id
    //     this.$emit('set-active-task', this.selectedId, taskId || '')
    //
    //     this.commandText = ''
    //     this.commandCandidatesLoadedFor = ''
    //     await this.loadCommandCandidates(this.selectedId)
    //   } catch (e) {
    //     this.$emit('append-output', this.selectedId, formatTerminalCommandFailedLine(e.message || 'unknown error'), 'error')
    //     ElMessage.error(e.message || 'Command failed')
    //     this.commandText = ''
    //   } finally {
    //     this.sending = false
    //   }
    // },


    handleLocalFrontendCommand(command) {
  const normalizedCommand = String(command || '').trim().toLowerCase()

  const localCommandHandlers = {
    clear: () => {
      this.$emit('clear-output')
      this.commandText = ''
      ElMessage.success('Console cleared')
    },

    cls: () => {
      this.$emit('clear-output')
      this.commandText = ''
      ElMessage.success('Console cleared')
    },
  }

  const handler = localCommandHandlers[normalizedCommand]

  if (!handler) {
    return false
  }

  handler()
  return true
},

    // Viewer actions are ordinary terminal commands. Presentation stays in the UI:
    // neither this submission nor the API receives UI-specific metadata.
    async submitViewerCommand(command, expectedClientId, echoToTerminal) {
      const text = String(command || '').trim()
      const clientId = String(this.selectedId || '')
      if (!text || !clientId || clientId !== String(expectedClientId || '')) {
        ElMessage.warning('The target device has changed')
        return ''
      }
      if (this.sending || this.hasRunningWebTask) {
        ElMessage.warning('A command is already running')
        return ''
      }

      this.sending = true
      if (echoToTerminal) this.$emit('append-output', clientId, '> ' + text, 'command')
      try {
        const data = await sendCommandApi(clientId, text, this.getTabScopedHeaders())
        const taskId = String(data?.task_id || '')
        this.$emit('set-active-task', clientId, taskId)
        return taskId
      } catch (error) {
        if (echoToTerminal) {
          this.$emit('append-output', clientId, formatTerminalCommandFailedLine(error.message || 'unknown error'), 'error')
        }
        ElMessage.error(error.message || 'Command failed')
        return ''
      } finally {
        this.sending = false
      }
    },

    async runResultActionCommand(command, expectedClientId, presentation = 'terminal') {
      return this.submitViewerCommand(command, expectedClientId, presentation !== 'dialog')
    },

    async runJsonViewerRefreshCommand(command, expectedClientId) {
      return this.submitViewerCommand(command, expectedClientId, true)
    },

    async runCommandText(command) {
  const normalizedCommand = String(command || '').trim()
  if (!normalizedCommand) {
    ElMessage.warning('No command to run')
    return
  }

  this.commandText = normalizedCommand
  await this.sendCommand()
},

    async cancelCurrentTask() {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      const taskId = String(this.currentActiveTaskId || '').trim()
      if (!taskId) {
        ElMessage.warning('No running task')
        return
      }

      this.cancelSending = true

      try {
        await cancelTask(taskId)

        this.$emit('append-output', this.selectedId, formatTerminalCancelRequestedLine(taskId), 'info')
        ElMessage.success('Cancel request sent')
      } catch (e) {
        this.cancelSending = false
        ElMessage.error(e.message || 'Cancel failed')
      }
    },

    async queryCommandCandidates(queryString, callback) {
      const effectiveQueryString = this.getAutocompleteCandidateQueryString(queryString)
      const emitCandidates = (items) => {
        const list = Array.isArray(items) ? items : []
        this.setAutocompleteCandidateItems(list, effectiveQueryString)
        callback(list)
      }
      const variableQuery = this.parseVariableCompletionQuery(effectiveQueryString)

      if (variableQuery) {
        emitCandidates(this.buildVariableCompletionCandidates(variableQuery))
        return
      }

      const completionQuery = this.parseCommandCompletionCandidateQuery(effectiveQueryString)

      if (completionQuery) {
        emitCandidates(await this.buildCommandCompletionCandidates(completionQuery))
        return
      }

      await this.ensureCommandCandidatesLoaded()

      const keyword = String(effectiveQueryString || '').trim().toLowerCase()
      const sourceList = Array.isArray(this.commandCandidates) ? this.commandCandidates : []
      const visibleCandidates = this.filterExecScriptCandidatesByCurrentOs(sourceList)

      if (!keyword) {
        emitCandidates(visibleCandidates)
        return
      }

      emitCandidates(this.filterCandidatesByTitle(visibleCandidates, keyword))
    },

    parseVariableCompletionQuery(queryString) {
      const rawText = String(queryString || '')
      const match = rawText.match(/\$\{([^{}]*)$/)

      if (!match) {
        return null
      }

      const tokenText = String(match[1] || '')
      const tokenStart = Number(match.index)

      if (!Number.isInteger(tokenStart) || tokenStart < 0) {
        return null
      }

      const normalizedToken = tokenText.replace('\\:', ':')
      const separatorIndex = normalizedToken.indexOf(':')

      return {
        rawText,
        tokenText,
        tokenStart,
        commandPrefix: rawText.slice(0, tokenStart),
        namespaceText: separatorIndex >= 0
          ? normalizedToken.slice(0, separatorIndex).trim().toLowerCase()
          : normalizedToken.trim().toLowerCase(),
        nameText: separatorIndex >= 0
          ? normalizedToken.slice(separatorIndex + 1).trim().toLowerCase()
          : '',
        hasNamespaceSeparator: separatorIndex >= 0,
      }
    },

    buildVariableCompletionCandidates(variableQuery) {
      const manifest = Array.isArray(this.currentConnection?.variable_manifest)
        ? this.currentConnection.variable_manifest
        : []

      if (!variableQuery?.hasNamespaceSeparator) {
        return this.buildVariableNamespaceCandidates(variableQuery, manifest)
      }

      const namespace = String(variableQuery.namespaceText || '').trim().toLowerCase()
      const nameKeyword = String(variableQuery.nameText || '').trim().toLowerCase()

      if (!namespace) {
        return []
      }

      return manifest
        .filter(item => String(item?.namespace || '').trim().toLowerCase() === namespace)
        .flatMap((item) => {
          const candidateNames = Array.isArray(item?.candidates) && item.candidates.length
            ? item.candidates
            : [item?.name]

          return candidateNames.map((candidateName) => {
            const name = String(candidateName || '').trim()
            if (!name) return null

            const normalizedName = name.toLowerCase()
            if (nameKeyword && !normalizedName.includes(nameKeyword)) {
              return null
            }

            const variableTemplate = Array.isArray(item?.candidates) && item.candidates.length
              ? '${' + namespace + ':' + name + '}'
              : String(item?.template || '').trim()

            if (!variableTemplate) return null

            return {
              name: variableTemplate,
              value: `${variableQuery.commandPrefix}${variableTemplate}`,
              template: `${variableQuery.commandPrefix}${variableTemplate}`,
              displayText: variableTemplate,
              help: String(item?.description || '').trim(),
              source: 'variable',
              group: `variable_${namespace}`,
              groupLabel: namespace,
              variableTemplate,
              variableName: normalizedName,
            }
          })
        })
        .filter(Boolean)
        .sort((left, right) => {
          const leftName = String(left?.variableName || '').toLowerCase()
          const rightName = String(right?.variableName || '').toLowerCase()
          const leftPrefix = nameKeyword && leftName.startsWith(nameKeyword) ? 0 : 1
          const rightPrefix = nameKeyword && rightName.startsWith(nameKeyword) ? 0 : 1
          return leftPrefix - rightPrefix || leftName.localeCompare(rightName)
        })
    },

    buildVariableNamespaceCandidates(variableQuery, manifest) {
      const namespaceKeyword = String(variableQuery?.namespaceText || '').trim().toLowerCase()
      const namespaces = []
      const seen = new Set()

      ;(Array.isArray(manifest) ? manifest : []).forEach((item) => {
        const namespace = String(item?.namespace || '').trim().toLowerCase()
        if (!namespace || seen.has(namespace)) return
        seen.add(namespace)
        namespaces.push(namespace)
      })

      return namespaces
        .filter(namespace => !namespaceKeyword || namespace.startsWith(namespaceKeyword))
        .map(namespace => {
          const namespaceTemplate = '${' + namespace + ':'
          return {
            name: namespaceTemplate,
            value: `${variableQuery.commandPrefix}${namespaceTemplate}`,
            template: `${variableQuery.commandPrefix}${namespaceTemplate}`,
            displayText: namespaceTemplate,
            help: `Complete ${namespace} variables`,
            source: 'variable_namespace',
            group: 'variable_namespace',
            groupLabel: 'variable',
            continueAutocomplete: true,
          }
        })
    },

    parseCommandCompletionCandidateQuery(queryString) {
      const rawText = String(queryString || '')
      const leftTrimmedText = rawText.trimStart()

      if (/^!\d*$/.test(leftTrimmedText)) {
        return {
          rawText,
          commandName: '!',
          requestInput: '!',
          cacheKey: this.buildCommandCompletionCandidateCacheKey('history_shortcut', 'quick'),
          requiresRemoteClient: false,
        }
      }

      const commandMatch = leftTrimmedText.match(/^([^\s]+)(?:\s+(.*))?$/)

      if (!commandMatch) {
        return null
      }

      const fileSystemRule = this.resolveFileSystemCompletionRule(leftTrimmedText)

      if (fileSystemRule) {
        return this.buildFileSystemCommandCompletionQuery(
          fileSystemRule.commandPrefix,
          rawText,
          fileSystemRule.argumentText,
          fileSystemRule,
        )
      }

      const commandName = String(commandMatch[1] || '').trim().toLowerCase()
      const argumentText = String(commandMatch[2] || '')
      const dynamicCommands = ['gopin', 'set', 'history', 'alias', 'httpctl', 'script', 'job', 'xt']

      if (!dynamicCommands.includes(commandName)) {
        return null
      }

      if (commandName === 'xt') {
        return this.buildXtCommandCompletionQuery(rawText, argumentText)
      }

      return {
        rawText,
        commandName,
        requestInput: `${commandName} `,
        cacheKey: this.buildCommandCompletionCandidateCacheKey(commandName, commandName),
        requiresRemoteClient: commandName === 'set',
      }
    },

    resolveFileSystemCompletionRule(inputText) {
      const rules = [
        ...DIRECTORY_ONLY_COMPLETION_COMMANDS.map(commandPrefix => ({
          commandPrefix,
          proxyCommand: 'cd',
          mode: 'directory',
        })),
        ...PATH_COMPLETION_COMMANDS.map(commandPrefix => ({
          commandPrefix,
          proxyCommand: 'download',
          mode: 'path',
        })),
      ].sort((left, right) => right.commandPrefix.length - left.commandPrefix.length)
      const text = String(inputText || '')
      const normalizedText = text.toLowerCase()

      for (const rule of rules) {
        const normalizedCommandPrefix = String(rule.commandPrefix || '').toLowerCase()
        if (!normalizedCommandPrefix || !normalizedText.startsWith(normalizedCommandPrefix)) {
          continue
        }

        const restText = text.slice(normalizedCommandPrefix.length)
        if (restText && !/^\s/.test(restText)) {
          continue
        }

        return {
          ...rule,
          argumentText: restText.replace(/^\s+/, ''),
        }
      }

      return null
    },

    buildFileSystemCommandCompletionQuery(commandName, rawText, argumentText, rule = null) {
      const pathParts = this.splitFileSystemCandidatePath(argumentText)
      const proxyCommand = String(rule?.proxyCommand || commandName || '').trim().toLowerCase()
      const commandPrefix = String(rule?.commandPrefix || commandName || '').trim().toLowerCase()
      const requestInput = `${proxyCommand} ${pathParts.candidatePrefix}`

      return {
        rawText,
        commandName: commandPrefix,
        requestInput,
        cacheKey: this.buildCommandCompletionCandidateCacheKey(commandPrefix, pathParts.lookupPath),
        requiresRemoteClient: true,
        fileSystemProxyCommand: proxyCommand,
        fileSystemTargetCommand: commandPrefix,
        fileSystemCompletionMode: String(rule?.mode || 'path'),
      }
    },

    buildXtCommandCompletionQuery(rawText, argumentText) {
      const subcommand = String(argumentText || '').trim().split(/\s+/, 1)[0] || ''
      const contextKey = ['info', 'which', 'run'].includes(subcommand) ? subcommand : 'root'
      const requestInput = contextKey === 'root' ? 'xt ' : `xt ${contextKey} `

      return {
        rawText,
        commandName: 'xt',
        requestInput,
        cacheKey: this.buildCommandCompletionCandidateCacheKey('xt', contextKey),
        requiresRemoteClient: false,
      }
    },

    splitFileSystemCandidatePath(argumentText) {
      const text = String(argumentText || '').trim()

      if (!text) {
        return {
          lookupPath: '',
          candidatePrefix: '',
        }
      }

      const lastForwardSlashIndex = text.lastIndexOf('/')
      const lastBackwardSlashIndex = text.lastIndexOf('\\')
      const lastSeparatorIndex = Math.max(lastForwardSlashIndex, lastBackwardSlashIndex)

      if (lastSeparatorIndex < 0) {
        return {
          lookupPath: '',
          candidatePrefix: '',
        }
      }

      const hasTrailingSeparator = lastSeparatorIndex === text.length - 1

      if (hasTrailingSeparator) {
        return {
          // 输入 cd a/b/ 或 download a/b/ 时，候选应来自 a/b。
          lookupPath: text,
          candidatePrefix: text,
        }
      }

      return {
        // 输入 a/bc 时，候选应来自 a，并用 bc 做前端本地过滤。
        lookupPath: this.buildLookupPathBeforeLastSeparator(text, lastSeparatorIndex),
        candidatePrefix: text.slice(0, lastSeparatorIndex + 1),
      }
    },

    buildLookupPathBeforeLastSeparator(text, lastSeparatorIndex) {
      if (lastSeparatorIndex <= 0) {
        return text.slice(0, lastSeparatorIndex + 1)
      }

      // Windows 盘符根目录：C:\foo 应查询 C:\。
      if (lastSeparatorIndex === 2 && text.length >= 2 && text[1] === ':') {
        return text.slice(0, lastSeparatorIndex + 1)
      }

      return text.slice(0, lastSeparatorIndex)
    },

    async buildCommandCompletionCandidates(completionQuery) {
      const cacheKey = completionQuery.cacheKey
      const cachedCandidates = this.commandCompletionCandidatesByContext[cacheKey]

      if (Array.isArray(cachedCandidates)) {
        return this.filterCommandCompletionCandidates(cachedCandidates, completionQuery)
      }

      if (completionQuery.requiresRemoteClient && this.hasRunningWebTask) {
        return []
      }

      const shouldLoad = await this.waitForCommandCompletionDebounce()
      if (!shouldLoad || !this.isCurrentCommandCompletionQuery(completionQuery)) {
        return []
      }

      const loadedCandidates = await this.loadCommandCompletionCandidatesForContext(completionQuery)
      if (!this.isCurrentCommandCompletionQuery(completionQuery)) {
        return []
      }

      return this.filterCommandCompletionCandidates(loadedCandidates, completionQuery)
    },

    async waitForCommandCompletionDebounce() {
      this.commandCompletionDebounceToken += 1
      const token = this.commandCompletionDebounceToken

      if (this.commandCompletionDebounceTimer) {
        clearTimeout(this.commandCompletionDebounceTimer)
        this.commandCompletionDebounceTimer = null
      }

      if (typeof this.commandCompletionDebounceResolve === 'function') {
        this.commandCompletionDebounceResolve(false)
      }

      return new Promise((resolve) => {
        this.commandCompletionDebounceResolve = resolve
        this.commandCompletionDebounceTimer = setTimeout(() => {
          this.commandCompletionDebounceTimer = null
          this.commandCompletionDebounceResolve = null
          resolve(token === this.commandCompletionDebounceToken)
        }, 260)
      })
    },

    isCurrentCommandCompletionQuery(completionQuery) {
      const currentText = this.getAutocompleteCandidateQueryString(this.commandText)
      const currentQuery = this.parseCommandCompletionCandidateQuery(currentText)

      if (!currentQuery) {
        return false
      }

      return currentQuery.cacheKey === completionQuery.cacheKey
    },

    buildCommandCompletionCandidateCacheKey(commandName, contextKey = '') {
      return [
        String(this.selectedId || '').trim(),
        String(this.currentConnection?.machine_id || '').trim(),
        this.getCurrentConnectionCwd(),
        String(commandName || '').trim().toLowerCase(),
        String(contextKey || '').trim(),
      ].join('::')
    },

    getCurrentConnectionCwd() {
      return String(this.currentConnection?.cwd || '').trim()
    },

    async loadCommandCompletionCandidatesForContext(completionQuery) {
      const cacheKey = completionQuery.cacheKey

      if (!this.selectedId || (completionQuery.requiresRemoteClient && this.hasRunningWebTask)) {
        return []
      }

      if (Array.isArray(this.commandCompletionCandidatesByContext[cacheKey])) {
        return this.commandCompletionCandidatesByContext[cacheKey]
      }

      if (this.commandCompletionCandidatesLoadPromises[cacheKey]) {
        return this.commandCompletionCandidatesLoadPromises[cacheKey]
      }

      // 动态补全按 provider 上下文懒加载，前端只做标题过滤和最多 50 项展示。
      this.commandCompletionCandidatesLoadPromises[cacheKey] = getCommandCompletions(this.selectedId, {
        raw_input: completionQuery.requestInput,
        cursor_position: completionQuery.requestInput.length,
        max_results: 0,
      })
        .then((payload) => {
          const items = Array.isArray(payload?.items) ? payload.items : []
          const normalizedItems = items
            .map(item => this.normalizeCommandCompletionCandidate(item, completionQuery))
            .filter(item => item.template)

          this.commandCompletionCandidatesByContext = {
            ...this.commandCompletionCandidatesByContext,
            [cacheKey]: normalizedItems,
          }

          return normalizedItems
        })
        .catch(() => [])
        .finally(() => {
          const nextPromises = { ...this.commandCompletionCandidatesLoadPromises }
          delete nextPromises[cacheKey]
          this.commandCompletionCandidatesLoadPromises = nextPromises
        })

      return this.commandCompletionCandidatesLoadPromises[cacheKey]
    },

    normalizeCommandCompletionCandidate(item, completionQuery) {
      const normalized = this.normalizeCandidateItem(item)
      if (!completionQuery?.fileSystemProxyCommand || !completionQuery?.fileSystemTargetCommand) {
        return normalized
      }

      return this.normalizeFileSystemCompletionCandidate(normalized, completionQuery)
    },

    normalizeFileSystemCompletionCandidate(item, completionQuery) {
      const sourcePrefix = `${completionQuery.fileSystemProxyCommand} `
      const targetPrefix = `${completionQuery.fileSystemTargetCommand} `
      const candidatePath = String(item?.candidatePath || '').trim()
      const template = candidatePath
        ? `${targetPrefix}${candidatePath}`.trim()
        : this.replaceCompletionCommandPrefix(item.template, sourcePrefix, targetPrefix)
      const value = candidatePath
        ? template
        : this.replaceCompletionCommandPrefix(item.value, sourcePrefix, targetPrefix)
      const name = candidatePath
        ? template
        : this.replaceCompletionCommandPrefix(item.name, sourcePrefix, targetPrefix)

      return {
        ...item,
        value,
        name,
        template,
        groupLabel: this.buildCandidateGroupLabel({ ...item, group: item.group, source: item.source }),
        searchText: this.getCandidateTitleText({ template, value, name }).toLowerCase(),
      }
    },

    replaceCompletionCommandPrefix(value, sourcePrefix, targetPrefix) {
      const text = String(value || '').trim()
      if (!text) return ''

      if (text.toLowerCase().startsWith(String(sourcePrefix || '').toLowerCase())) {
        return `${targetPrefix}${text.slice(String(sourcePrefix || '').length)}`.trim()
      }

      return text
    },

    filterCommandCompletionCandidates(candidates, completionQuery) {
      const keyword = String(completionQuery?.rawText || '').trim().toLowerCase()
      const list = Array.isArray(candidates) ? candidates : []

      if (!keyword) {
        return list.slice(0, 50)
      }

      return this.filterCandidatesByTitle(list, keyword).slice(0, 50)
    },

    clearCommandCompletionCandidateCache() {
      if (this.commandCompletionDebounceTimer) {
        clearTimeout(this.commandCompletionDebounceTimer)
        this.commandCompletionDebounceTimer = null
      }

      if (typeof this.commandCompletionDebounceResolve === 'function') {
        this.commandCompletionDebounceResolve(false)
      }

      this.commandCompletionDebounceResolve = null
      this.commandCompletionCandidatesByContext = {}
      this.commandCompletionCandidatesLoadPromises = {}
    },

    handleCommandTextUpdate(value) {
      this.clearAutocompleteNavigationState()
      this.autocompleteCandidateQueryText = ''
      this.commandText = String(value || '')
    },

    handleCommandInputKeydown(event) {
      const key = String(event?.key || '')

      if (key === 'ArrowDown' || key === 'ArrowUp') {
        if (this.previewAutocompleteCandidateByArrowKey(key)) {
          event.preventDefault()
          event.stopPropagation()
        }
        return
      }

      if (key === 'ArrowRight' && this.autocompleteNavigationPreviewActive) {
        event.preventDefault()
        event.stopPropagation()
        this.commitAutocompleteNavigationPreview()
        return
      }

      if (key === 'Escape' && this.autocompleteNavigationPreviewActive) {
        event.preventDefault()
        event.stopPropagation()
        this.restoreAutocompleteNavigationBaseText()
        return
      }

    },

    handleCandidateSelect(item) {
      if (!item) return
      this.applyAutocompleteCandidateToInput(item)
    },

    getAutocompleteCandidateQueryString(queryString) {
      if (this.autocompleteNavigationPreviewActive) {
        return this.autocompleteNavigationBaseText
      }

      return String(queryString || '')
    },

    setAutocompleteCandidateItems(items, queryString = '') {
      const normalizedQueryString = String(queryString || '')
      const list = Array.isArray(items) ? items : []
      const shouldKeepIndex = (
        this.autocompleteCandidateQueryText === normalizedQueryString &&
        this.autocompleteNavigationIndex >= 0 &&
        this.autocompleteNavigationIndex < list.length
      )

      this.autocompleteCandidateItems = list
      this.autocompleteCandidateQueryText = normalizedQueryString

      if (!shouldKeepIndex) {
        this.autocompleteNavigationIndex = -1
        return
      }

      this.highlightAutocompleteCandidate(this.autocompleteNavigationIndex)
    },

    clearAutocompleteNavigationState() {
      this.autocompleteNavigationBaseText = ''
      this.autocompleteNavigationIndex = -1
      this.autocompleteNavigationPreviewActive = false
    },

    restoreAutocompleteNavigationBaseText() {
      const baseText = this.autocompleteNavigationBaseText
      this.clearAutocompleteNavigationState()
      this.commandText = baseText
      this.closeAutocomplete()
    },

    commitAutocompleteNavigationPreview() {
      const committedText = String(this.commandText || '')

      if (!committedText) {
        this.clearAutocompleteNavigationState()
        return
      }

      // 右方向键只提交 preview，不执行命令、不刷新 provider、不关闭候选列表。
      // 继续输入 / 时，会按正常输入变更触发下一层 filesystem completion。
      const committedIndex = this.autocompleteNavigationIndex
      const committedCandidate = this.autocompleteCandidateItems[committedIndex]
      this.autocompleteNavigationBaseText = ''
      this.autocompleteNavigationPreviewActive = false
      this.autocompleteNavigationIndex = committedIndex
      this.autocompleteCandidateQueryText = committedText
      this.commandText = committedText
      this.highlightAutocompleteCandidate(committedIndex)
      this.focusInput()

      if (committedCandidate?.continueAutocomplete) {
        this.refreshAutocompleteSuggestionsForCurrentText()
      }
    },

    refreshAutocompleteSuggestionsForCurrentText() {
      this.$nextTick(() => {
        const input = this.$refs.commandInputRef
        const queryText = String(this.commandText || '')

        if (input && typeof input.getData === 'function') {
          input.getData(queryText)
          return
        }

        if (input && typeof input.handleChange === 'function') {
          input.handleChange(queryText)
          return
        }

        this.focusInput()
      })
    },

    previewAutocompleteCandidateByArrowKey(key) {
      const candidates = Array.isArray(this.autocompleteCandidateItems) ? this.autocompleteCandidateItems : []

      const expectedQueryString = this.getAutocompleteCandidateQueryString(this.commandText)

      if (!candidates.length || this.autocompleteCandidateQueryText !== expectedQueryString) {
        return false
      }

      const currentIndex = this.autocompleteNavigationIndex
      const nextIndex = key === 'ArrowUp'
        ? this.getPreviousAutocompleteCandidateIndex(currentIndex, candidates.length)
        : this.getNextAutocompleteCandidateIndex(currentIndex, candidates.length)
      const nextCandidate = candidates[nextIndex]
      const nextCommandText = this.getCandidateInsertText(nextCandidate)

      if (!nextCommandText) {
        return false
      }

      // 导航预览只改 input 展示，候选列表仍按原始输入过滤，避免选不到后续项。
      if (!this.autocompleteNavigationPreviewActive) {
        this.autocompleteNavigationBaseText = String(this.commandText || '')
      }

      this.autocompleteNavigationPreviewActive = true
      this.autocompleteNavigationIndex = nextIndex
      this.commandText = nextCommandText
      this.highlightAutocompleteCandidate(nextIndex)

      return true
    },

    getPreviousAutocompleteCandidateIndex(currentIndex, total) {
      if (!Number.isInteger(currentIndex) || currentIndex <= 0) {
        return total - 1
      }

      return currentIndex - 1
    },

    getNextAutocompleteCandidateIndex(currentIndex, total) {
      if (!Number.isInteger(currentIndex) || currentIndex < 0 || currentIndex >= total - 1) {
        return 0
      }

      return currentIndex + 1
    },


    highlightAutocompleteCandidate(index) {
      this.$nextTick(() => {
        const input = this.$refs.commandInputRef

        if (input && typeof input.highlight === 'function') {
          input.highlight(index)
        }
      })
    },

    handleAutocompleteCandidateMouseEnter(item) {
      const index = this.findAutocompleteCandidateIndex(item)

      if (index < 0) return

      this.autocompleteNavigationIndex = index

      if (this.autocompleteNavigationPreviewActive) {
        const text = this.getCandidateInsertText(item)
        if (text) {
          this.commandText = text
        }
      }
    },

    findAutocompleteCandidateIndex(item) {
      const candidates = Array.isArray(this.autocompleteCandidateItems) ? this.autocompleteCandidateItems : []
      const sameReferenceIndex = candidates.indexOf(item)

      if (sameReferenceIndex >= 0) {
        return sameReferenceIndex
      }

      const titleText = this.getCandidateTitleText(item)
      if (!titleText) {
        return -1
      }

      return candidates.findIndex(candidate => this.getCandidateTitleText(candidate) === titleText)
    },

    applyAutocompleteCandidateToInput(item) {
      const text = this.getCandidateInsertText(item)

      if (!text) return

      this.clearAutocompleteNavigationState()
      this.commandText = text
      this.focusInput()

      if (item?.continueAutocomplete) {
        this.refreshAutocompleteSuggestionsForCurrentText()
      }
    },

    getCandidateInsertText(item) {
      return String(item?.template || item?.value || item?.name || '').trim()
    },

    filterCandidatesByTitle(candidates, keyword) {
      const normalizedKeyword = String(keyword || '').trim().toLowerCase()
      const exactMatches = []
      const prefixMatches = []
      const textMatches = []
      const fuzzyMatches = []

      ;(Array.isArray(candidates) ? candidates : []).forEach((item) => {
        const titleText = this.getCandidateTitleSearchText(item)

        if (!titleText) return

        if (titleText === normalizedKeyword) {
          exactMatches.push(item)
          return
        }

        if (titleText.startsWith(normalizedKeyword)) {
          prefixMatches.push(item)
          return
        }

        if (titleText.includes(normalizedKeyword)) {
          textMatches.push(item)
          return
        }

        // 仍然只基于标题筛选；script exec 仅按脚本路径/文件名做保守模糊匹配。
        if (this.isExecScriptPathCandidateMatch(item, normalizedKeyword)) {
          fuzzyMatches.push(item)
        }
      })

      return [
        ...exactMatches,
        ...prefixMatches,
        ...textMatches,
        ...fuzzyMatches,
      ]
    },

    isExecScriptPathCandidateMatch(item, keyword) {
      if (!this.isExecScriptCandidate(item)) return false

      const scriptPath = this.getExecScriptPathSearchText(item)
      const queryText = String(keyword || '').trim().toLowerCase().replace(/^script\s+exec\s+/, '')
      const tokens = queryText.split(/\s+/).filter(Boolean)

      if (!scriptPath || !tokens.length) return false

      // 不做字符子序列匹配，避免 app 误命中 machine_fingerprint.py 这类路径。
      return tokens.every(token => scriptPath.includes(token))
    },

    getExecScriptPathSearchText(item) {
      const metadataScript = String(item?.metadata?.script || item?.script || '').trim()
      if (metadataScript) return metadataScript.toLowerCase()

      return this.getCandidateTitleText(item)
        .replace(/^script\s+exec\s+/i, '')
        .trim()
        .toLowerCase()
    },

    getCandidateTitleText(item) {
      return String(item?.template || item?.value || item?.name || '').trim()
    },

    getCandidateTitleSearchText(item) {
      return this.getCandidateTitleText(item).toLowerCase()
    },

    async ensureCommandCandidatesLoaded() {
      if (!this.selectedId) return

      if (this.commandCandidatesLoadedFor === this.selectedId && this.commandCandidates.length) {
        return
      }

      await this.loadCommandCandidates(this.selectedId)
    },

    async reloadCommandCandidates(options = {}) {
      if (options?.reset) {
        this.commandCandidatesLoadedFor = ''
      }

      if (!this.selectedId) return

      await this.loadCommandCandidates(this.selectedId)
    },

    async loadCommandCandidates(clientId) {
      if (!clientId) return

      if (this.commandCandidatesLoadPromise) {
        return this.commandCandidatesLoadPromise
      }

      this.commandCandidatesLoadPromise = this.loadCommandCandidatesInternal(clientId)
        .finally(() => {
          this.commandCandidatesLoadPromise = null
        })

      return this.commandCandidatesLoadPromise
    },

    async loadCommandCandidatesInternal(clientId) {
      const historyMachineId = this.resolveCommandHistoryMachineId(clientId)

      try {
        const [candidateData, historyData] = await Promise.all([
          getCommandCandidates(clientId),
          getCommandHistory(historyMachineId),
        ])

        const systemCandidates = Array.isArray(candidateData) ? candidateData : []
const historyItems = Array.isArray(historyData) ? historyData : []
const pinnedHistoryItems = historyItems.filter(item => item && item.is_pinned)

        // const systemCandidates = Array.isArray(candidateJson.data) ? candidateJson.data : []
        // const historyItems = Array.isArray(historyJson.data) ? historyJson.data : []

        const merged = []
        const seen = new Set()

        const pushUniqueCandidate = (item) => {
          const normalized = this.normalizeCandidateItem(item)
          const template = normalized.template

          if (!template || seen.has(template)) return
          seen.add(template)
          merged.push(normalized)
        }

        const visibleSystemCandidates = systemCandidates.filter(item => item.suggest !== false)

        const clientCandidates = visibleSystemCandidates.filter(
          item => item.source === 'client' && item.group !== 'acmd',
        )
        const acmdCandidates = visibleSystemCandidates.filter(
          item => item.source === 'client' && item.group === 'acmd',
        )
        const serverCandidates = visibleSystemCandidates.filter(item => item.source === 'server')
        const aliasCandidates = visibleSystemCandidates.filter(item => item.source === 'alias')
        const scriptCandidates = visibleSystemCandidates.filter(item => item.source === 'script')
        const commonOpsCandidates = this.buildCommonOpsCandidates()

        clientCandidates.forEach(pushUniqueCandidate)
        acmdCandidates.forEach(pushUniqueCandidate)
        serverCandidates.forEach(pushUniqueCandidate)
        commonOpsCandidates.forEach(pushUniqueCandidate)
        aliasCandidates.forEach(pushUniqueCandidate)
        scriptCandidates.forEach(pushUniqueCandidate)

        // historyItems.forEach((item) => {
        //   const command = String(item.command || '').trim()
        //   if (!command || seen.has(command)) return
        //
        //   seen.add(command)
        //   merged.push(this.normalizeCandidateItem({
        //     name: command,
        //     template: command,
        //     help: 'Recent command',
        //     source: 'history',
        //     group: 'history',
        //   }))
        // })

        pinnedHistoryItems.forEach((item) => {
  const command = String(item.command || '').trim()
  if (!command || seen.has(command)) return

  seen.add(command)
  merged.push(this.normalizeCandidateItem({
    name: command,
    template: command,
    help: 'Pinned recent command',
    source: 'history',
    group: 'history',
  }))
})

        // history run / !<index> 已统一由 CommandCompletionProvider 提供。
        this.commandCandidates = merged
        this.commandCandidatesLoadedFor = clientId
      } catch (_error) {
        this.commandCandidates = []
        this.commandCandidatesLoadedFor = ''
      }
    },

    resolveCommandHistoryMachineId(clientId) {
      if (String(this.currentConnection?.client_id || '') !== String(clientId || '')) {
        return ''
      }

      return String(this.currentConnection?.machine_id || '').trim()
    },

    buildCommonOpsCandidates() {
      return [
        {
          name: 'whoami',
          template: 'whoami',
          help: 'Show current user',
          source: 'common_ops',
          group: 'common_ops',
        },
        {
          name: 'hostname',
          template: 'hostname',
          help: 'Show host name',
          source: 'common_ops',
          group: 'common_ops',
        },
        {
          name: 'mkdir',
          template: 'mkdir ',
          help: 'Create a directory',
          source: 'common_ops',
          group: 'common_ops',
        },
        {
          name: 'rmdir',
          template: 'rmdir ',
          help: 'Remove an empty directory',
          source: 'common_ops',
          group: 'common_ops',
        },
      ]
    },

    buildCandidateGroupLabel(item) {
      const groupText = String(item.group || item.source || '').trim()
      if (!groupText) return ''
      return groupText
    },

    normalizeCandidateItem(item) {
      const rawValue = String(item.value || '').trim()
      const template = String(item.template || rawValue || '').trim()
      const name = String(item.name || template || rawValue || '').trim()
      const help = String(item.help || '').trim()
      const group = String(item.group || '').trim()
      const source = String(item.source || '').trim()
      const groupLabel = this.buildCandidateGroupLabel(item)
      const titleText = this.getCandidateTitleText({ template, value: rawValue, name })

      return {
        ...item,
        value: template,
        name,
        template,
        help,
        group,
        source,
        groupLabel,
        searchText: titleText.toLowerCase(),
      }
    },

    buildQuickHistoryShortcutCandidates(historyItems) {
      const items = Array.isArray(historyItems) ? historyItems : []

      return items
        .map((item) => {
          const indexValue = Number.parseInt(item && item.index, 10)
          const commandText = String((item && item.command) || '').trim()

          if (!Number.isInteger(indexValue) || indexValue <= 0 || !commandText) {
            return null
          }

          const shortcutText = `!${indexValue}`
          return {
            name: shortcutText,
            value: shortcutText,
            template: shortcutText,
            help: commandText,
            source: 'quick_history_shortcut',
            group: 'quick_history',
            groupLabel: 'quick_history',
            quickHistoryIndex: indexValue,
            quickHistoryCommand: commandText,
            searchText: shortcutText.toLowerCase(),
          }
        })
        .filter(Boolean)
    },

    filterExecScriptCandidatesByCurrentOs(candidates) {
      const currentOsAlias = this.normalizeCurrentOsAlias(this.currentConnection?.os_alias)

      if (!currentOsAlias) {
        return Array.isArray(candidates) ? candidates : []
      }

      return (Array.isArray(candidates) ? candidates : []).filter(item => {
        return this.shouldShowCandidateForCurrentOs(item, currentOsAlias)
      })
    },

    shouldShowCandidateForCurrentOs(item, currentOsAlias) {
      if (!this.isExecScriptCandidate(item)) {
        return true
      }

      const scriptRoot = this.getExecScriptRoot(item)
      if (!scriptRoot) {
        return false
      }

      const normalizedRoot = this.normalizeExecScriptRoot(scriptRoot)

      return normalizedRoot === 'common' || normalizedRoot === currentOsAlias
    },

    isExecScriptCandidate(item) {
      if (!item) return false

      const source = String(item.source || '').trim().toLowerCase()
      const group = String(item.group || '').trim().toLowerCase()
      const groupLabel = String(item.groupLabel || '').trim().toLowerCase()
      const commandText = this.getCandidateCommandText(item)

      return (
        source === 'script' ||
        group === 'script' ||
        groupLabel === 'script' ||
        /^script\s+exec\s+/i.test(commandText)
      )
    },

    getCandidateCommandText(item) {
      return String(item?.template || item?.value || item?.name || '').trim()
    },

    getExecScriptRoot(item) {
      const commandText = this.getCandidateCommandText(item)
      const match = commandText.match(/^script\s+exec\s+(.+)$/i)

      if (!match) return ''

      const scriptPath = this.stripCommandArgumentQuotes(match[1])
        .replace(/\\/g, '/')
        .trim()

      return scriptPath.split('/').filter(Boolean)[0] || ''
    },

    stripCommandArgumentQuotes(value) {
      const text = String(value || '').trim()
      if (!text) return ''

      const firstChar = text[0]
      const quoteChars = ['"', "'"]

      if (!quoteChars.includes(firstChar)) {
        return text.split(/\s+/)[0] || ''
      }

      const endIndex = text.indexOf(firstChar, 1)
      if (endIndex === -1) {
        return text.slice(1)
      }

      return text.slice(1, endIndex)
    },

    normalizeCurrentOsAlias(value) {
      const text = String(value || '').trim().toLowerCase()

      if (!text) return ''
      if (['windows', 'win', 'win32', 'nt'].includes(text)) return 'win'
      if (['darwin', 'mac', 'macos', 'osx'].includes(text)) return 'mac'
      if (['linux', 'ubuntu', 'debian', 'centos', 'fedora', 'redhat', 'rhel', 'alpine', 'arch'].includes(text)) return 'linux'
      if (['ios', 'iphone', 'ipad', 'iphoneos', 'ipados'].includes(text)) return 'ios'

      if (text.includes('win')) return 'win'
      if (text.includes('darwin') || text.includes('mac')) return 'mac'
      if (text.includes('linux')) return 'linux'
      if (/(ubuntu|debian|centos|fedora|redhat|rhel|alpine|arch)/.test(text)) return 'linux'
      if (text.includes('ios') || text.includes('iphone') || text.includes('ipad')) return 'ios'

      return text
    },

    normalizeExecScriptRoot(value) {
      const text = String(value || '').trim().toLowerCase()

      if (!text) return ''
      if (['common', 'shared'].includes(text)) return 'common'
      if (['windows', 'win', 'win32', 'nt'].includes(text)) return 'win'
      if (['darwin', 'mac', 'macos', 'osx'].includes(text)) return 'mac'
      if (['linux', 'ubuntu', 'debian', 'centos', 'fedora', 'redhat', 'rhel', 'alpine', 'arch'].includes(text)) return 'linux'
      if (['ios', 'iphone', 'ipad', 'iphoneos', 'ipados'].includes(text)) return 'ios'

      return text
    },

    sortQuickHistoryShortcutCandidates(items) {
      const list = Array.isArray(items) ? [...items] : []

      return list.sort((a, b) => {
        const ai = Number.parseInt(a && a.quickHistoryIndex, 10)
        const bi = Number.parseInt(b && b.quickHistoryIndex, 10)

        const av = Number.isInteger(ai) ? ai : Number.MAX_SAFE_INTEGER
        const bv = Number.isInteger(bi) ? bi : Number.MAX_SAFE_INTEGER

        return av - bv
      })
    },

    getTabScopedHeaders(extra = {}) {
      const headers = { ...extra }
      const normalizedTabId = String(this.tabId || '').trim()

      if (normalizedTabId) {
        headers['X-Tab-Id'] = normalizedTabId
      }

      return headers
    },

    setCommandText(value) {
      this.commandText = String(value || '')
      this.focusInput()
    },

    focusInput() {
      const input = this.$refs.commandInputRef

      if (input && typeof input.focus === 'function') {
        input.focus()
      }
    },

    closeAutocomplete() {
      const input = this.$refs.commandInputRef

      if (input && typeof input.close === 'function') {
        input.close()
      }
    },
  },
}
</script>

<style scoped>
/* 命令输入栏 */
.command-row {
  display: block;
  padding: 14px 15px;
  border-bottom: 1px solid var(--terminal-line);
  background: rgba(2, 6, 23, 0.34);
  flex-shrink: 0;
}

.command-box {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 88px 88px;
  gap: 10px;
  align-items: center;
  min-width: 0;
}

.command-box-full {
  width: 100%;
}

.command-autocomplete-shell {
  width: 100%;
  min-width: 0;
}

.run-button {
  width: 88px;
  height: 42px;
  border: none;
  outline: none;
  border-radius: 12px;
  background: #2563eb;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.run-button:not(:disabled):not(.is-disabled):hover {
  background: #1d4ed8;
}

.run-button:disabled,
.run-button.is-disabled {
  background: rgba(71, 85, 105, 0.72) !important;
  border: 1px solid rgba(148, 163, 184, 0.16) !important;
  color: rgba(226, 232, 240, 0.52) !important;
  cursor: not-allowed !important;
  opacity: 1 !important;
  box-shadow: none !important;
}

.cancel-button {
  background: #dc2626 !important;
  color: #fff !important;
}

.cancel-button:not(:disabled):not(.is-disabled):not(.is-loading):hover {
  background: #b91c1c !important;
  color: #fff !important;
}

.cancel-button:disabled,
.cancel-button.is-disabled {
  background: rgba(127, 29, 29, 0.34) !important;
  border: 1px solid rgba(248, 113, 113, 0.16) !important;
  color: rgba(254, 202, 202, 0.46) !important;
  cursor: not-allowed !important;
  opacity: 1 !important;
  box-shadow: none !important;
}

.cancel-button.is-loading {
  background: #b91c1c !important;
  color: #fff !important;
  cursor: default !important;
  opacity: 1 !important;
}

@media (max-width: 640px) {
  .command-box {
    grid-template-columns: minmax(0, 1fr) 80px 80px;
  }

  .run-button {
    width: 80px;
  }
}

@media (max-width: 960px) {
  .command-row {
    position: sticky;
    top: 0;
    top: env(safe-area-inset-top, 0px);
    z-index: 80;
    padding: 12px 12px 14px;
    background: rgba(2, 6, 23, 0.92);
    -webkit-backdrop-filter: blur(12px);
    backdrop-filter: blur(12px);
    box-shadow: 0 10px 24px rgba(2, 6, 23, 0.22);
  }

  .command-box {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 10px;
    align-items: stretch;
  }

  .command-autocomplete-shell {
    grid-column: 1 / -1;
    width: 100%;
    min-width: 0;
  }

  .run-button {
    width: 100%;
    height: 38px;
  }

  .run-button:not(.cancel-button) {
    grid-column: 1 / 2;
  }

  .cancel-button {
    grid-column: 2 / 3;
    margin-left: 0 !important;
  }
}
</style>

<style>
/* CommandInputBar: Element Plus 内部输入框样式必须放非 scoped，避免 el-input 内部 DOM 吃不到样式。 */
.command-autocomplete,
.command-autocomplete .el-input,
.command-autocomplete .el-input__wrapper {
  width: 100%;
  min-width: 0;
}

.command-autocomplete .el-input__wrapper {
  height: 42px;
  padding: 0 14px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  outline: none;
  background: rgba(255, 255, 255, 0.06) !important;
  box-shadow: none !important;
}

.command-autocomplete .el-input__wrapper:hover {
  box-shadow: none !important;
}

.command-autocomplete .el-input__wrapper.is-focus {
  border-color: rgba(96, 165, 250, 0.5);
  box-shadow: none !important;
}

.command-autocomplete.command-autocomplete-preview .el-input__wrapper {
  border-color: rgba(251, 191, 36, 0.55);
  background: rgba(251, 191, 36, 0.08) !important;
  box-shadow: inset 0 0 0 1px rgba(251, 191, 36, 0.16) !important;
}

.command-autocomplete.command-autocomplete-preview .el-input__inner {
  color: rgba(248, 250, 252, 0.78) !important;
}

.command-autocomplete .el-input__inner {
  height: 100%;
  color: #f8fafc !important;
  font-size: 14px;
  background: transparent !important;
}

.command-autocomplete .el-input__inner::placeholder {
  color: #8ea2c0 !important;
}

.command-autocomplete-popper {
  background: #0f172a !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  border-radius: 12px !important;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35) !important;
  overflow: hidden;
}

.command-autocomplete-popper .el-autocomplete-suggestion__wrap {
  padding: 8px 0;
  background: #0f172a !important;
}

.command-autocomplete-popper .el-scrollbar,
.command-autocomplete-popper .el-scrollbar__wrap,
.command-autocomplete-popper .el-scrollbar__view {
  background: #0f172a !important;
}

.command-autocomplete-popper li {
  padding: 0 12px !important;
  line-height: normal !important;
  background: #0f172a !important;
}

.command-autocomplete-popper li:hover,
.command-autocomplete-popper li.highlighted {
  background: rgba(96, 165, 250, 0.12) !important;
}

.command-autocomplete-popper .command-autocomplete-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 2px;
}

.command-autocomplete-popper .command-autocomplete-item-main {
  min-width: 0;
  flex: 1;
}

.command-autocomplete-popper .command-autocomplete-item-name,
.command-autocomplete-popper .command-autocomplete-item-desc {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.command-autocomplete-popper .command-autocomplete-item-name {
  max-width: 520px;
  color: #f8fafc !important;
  font-size: 14px;
  line-height: 1.5;
  font-weight: 600;
}

.command-autocomplete-popper .command-autocomplete-item-desc {
  max-width: 640px;
  margin-top: 4px;
  color: #8ea2c0 !important;
  font-size: 12px;
  line-height: 1.5;
}

.command-autocomplete-popper .command-autocomplete-item-group {
  flex-shrink: 0;
  align-self: center;
  color: #60a5fa !important;
  font-size: 12px;
  line-height: 1.4;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.12) !important;
  border: 1px solid rgba(96, 165, 250, 0.18);
}

/*
//@media (max-width: 960px) {
//  .command-autocomplete,
//  .command-autocomplete .el-input,
//  .command-autocomplete .el-input__wrapper,
//  .command-autocomplete .el-textarea,
//  .command-autocomplete .el-textarea__inner {
//    width: 100%;
//    min-width: 0;
//  }
//
//  .command-autocomplete .el-input__wrapper {
//    height: 44px;
//  }
//
//  .command-autocomplete .el-textarea__inner,
//  .command-autocomplete-shell textarea {
//    min-height: 44px !important;
//    height: auto !important;
//    max-height: none !important;
//    overflow-y: hidden !important;
//    resize: none !important;
//  }
//}
*/

@media (max-width: 960px) {
  .command-autocomplete,
  .command-autocomplete .el-input,
  .command-autocomplete .el-input__wrapper,
  .command-autocomplete .el-textarea,
  .command-autocomplete .el-textarea__inner {
    width: 100%;
    min-width: 0;
  }

  .command-autocomplete .el-input__wrapper {
    height: 44px;
  }

  .command-autocomplete .el-textarea__inner,
  .command-autocomplete-shell textarea {
    min-height: 44px !important;
    height: auto !important;
    max-height: none !important;
    overflow-y: hidden !important;
    resize: none !important;
  }

  .command-autocomplete-popper {
    width: calc(100vw - 24px) !important;
    max-width: calc(100vw - 24px) !important;
    min-width: 0 !important;
    box-sizing: border-box;
  }

  .command-autocomplete-popper .el-autocomplete-suggestion,
  .command-autocomplete-popper .el-autocomplete-suggestion__wrap,
  .command-autocomplete-popper .el-scrollbar,
  .command-autocomplete-popper .el-scrollbar__wrap,
  .command-autocomplete-popper .el-scrollbar__view {
    width: 100% !important;
    max-width: 100% !important;
    min-width: 0 !important;
    box-sizing: border-box;
  }

  .command-autocomplete-popper .command-autocomplete-item-name,
  .command-autocomplete-popper .command-autocomplete-item-desc {
    max-width: calc(100vw - 120px);
  }
}
</style>