<template>
  <div
      class="terminal-output"
      :class="{ 'terminal-output-empty': !lines.length }"
      ref="terminalOutputRef"
  >
    <div v-if="!lines.length" class="terminal-empty">
      <div class="terminal-empty-title">Console ready</div>
      <div class="terminal-empty-text">
        Run a command to start streaming output from the selected device.
      </div>
    </div>

    <template v-else>
      <div
          v-for="block in terminalBlocks"
          :key="block.key"
          class="terminal-command-block"
          :class="{
            'terminal-command-block-actionable': canUseTerminalBlockActions(block),
            'terminal-command-block-collapsed': isTerminalBlockCollapsed(block),
          }"
      >
        <div
            v-if="block.commandLine"
            class="terminal-block-command-row"
        >
          <div
              class="terminal-line terminal-line-command"
              :class="`line-${block.commandLine.line.kind || 'default'}`"
          >
            <span class="terminal-prefix">$</span>
            <span class="terminal-text">{{ block.commandLine.line.text }}</span>
          </div>
        </div>

        <template
            v-for="entry in getVisibleTerminalBlockBodyLines(block)"
            :key="entry.index"
        >
          <template v-if="isCommandFinishedLine(entry.line)">
            <div
                v-if="!isTerminalBlockCollapsed(block) && getTerminalTailActionItems(lines, entry.index).length > 0"
                class="terminal-line"
                :class="`line-${entry.line.kind || 'default'}`"
            >
              <a
                  v-for="(actionItem, actionIndex) in getTerminalTailActionItems(lines, entry.index)"
                  :key="actionItem.key"
                  href="#"
                  class="table-action-link-aux terminal-text"
                  :class="{ 'terminal-action-link-spaced': actionIndex > 0 }"
                  @click.prevent.stop="handleTerminalActionClick(actionItem)"
              >
                [ {{ actionItem.type === 'preview' ? 'Preview' : 'View JSON' }} ]
              </a>
            </div>

            <div
                class="terminal-line terminal-command-finished-row"
                :class="`line-${entry.line.kind || 'default'}`"
            >
              <span class="terminal-text">{{ entry.line.text }}</span>
              <span
                  v-if="isTerminalBlockCollapsed(block)"
                  class="terminal-block-collapsed-badge"
              >
                Collapsed
              </span>

              <el-dropdown
                  v-if="canUseTerminalBlockActions(block)"
                  trigger="click"
                  placement="bottom-start"
                  popper-class="terminal-output-action-dropdown"
                  @command="handleTerminalBlockCommand(block, $event)"
              >
                <button
                    class="terminal-block-more"
                    type="button"
                    title="Output actions"
                    aria-label="Output actions"
                    @click.stop
                >
                  ⋯
                </button>

                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="toggle-collapse">
                      {{ isTerminalBlockCollapsed(block) ? 'Expand output' : 'Collapse output' }}
                    </el-dropdown-item>
                    <el-dropdown-item
                        command="copy-command"
                        :disabled="isTerminalRemoteUploadBlock(block) || isTerminalScriptRunBlock(block)"
                    >
                      Copy command
                    </el-dropdown-item>
                    <el-dropdown-item
                        command="rerun-command"
                        :disabled="isTerminalRemoteUploadBlock(block)"
                    >
                      Run again
                    </el-dropdown-item>
                    <el-dropdown-item
                        command="copy-output"
                        :disabled="!hasTerminalBlockOutput(block)"
                    >
                      Copy output
                    </el-dropdown-item>
                    <el-dropdown-item
                        command="save-output"
                        :disabled="isTerminalRemoteUploadBlock(block) || isSavingTerminalBlock(block) || !hasTerminalBlockOutput(block)"
                    >
                      Save output
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>

          <div
              v-else
              class="terminal-line"
              :class="[`line-${entry.line.kind || 'default'}`, {
                'terminal-warning-with-actions': entry.line.kind === 'warning' &&
                  (getSuggestedCommandAction(entry.line) || getClientRevisionDetails(entry.line)),
              }]"
          >
            <span
                v-if="entry.line.kind === 'command'"
                class="terminal-prefix"
            >$</span>

<!--            <span-->
<!--                v-if="!shouldParseTerminalLineLinks(entry.line)"-->
<!--                class="terminal-text"-->
<!--            >{{ entry.line.text }}</span>-->
<!--            <TerminalLinkedText-->
<!--                v-else-->
<!--                class="terminal-text"-->
<!--                :text="entry.line.text"-->
<!--            />-->

            <span
    v-if="!shouldParseTerminalLineLinks(entry.line)"
    class="terminal-text"
>{{ entry.line.text }}</span>

<span
    v-else
    class="terminal-text"
>
  <TerminalLinkedText :text="entry.line.text" />
</span>

            <a
                v-if="getSuggestedCommandAction(entry.line)"
                href="#"
                class="table-action-link-aux terminal-text terminal-action-link-spaced"
                @click.prevent.stop="handleSuggestedCommandClick(entry.line)"
            >
              [ {{ getSuggestedCommandAction(entry.line).label }} ]
            </a>

            <a
                v-if="getClientRevisionDetails(entry.line)"
                href="#"
                class="table-action-link-aux terminal-text terminal-action-link-spaced"
                @click.prevent.stop="openClientRevisionDetails(entry.line)"
            >
              [ Details ]
            </a>

            <a
                v-if="entry.line?.meta?.foregroundTaskNotice"
                href="#"
                class="table-action-link-aux terminal-text terminal-action-link-spaced"
                @click.prevent.stop="$emit('open-task-details')"
            >
              [ Details ]
            </a>

            <a
                v-for="(actionItem, actionIndex) in getTerminalInlineActionItems(lines, entry.index)"
                :key="actionItem.key"
                href="#"
                class="table-action-link-aux terminal-text"
                :class="{ 'terminal-action-link-spaced': actionIndex > 0 }"
                @click.prevent.stop="handleTerminalActionClick(actionItem)"
            >
              [ {{ actionItem.type === 'preview' ? 'Preview' : 'JSON' }} ]
            </a>
          </div>
        </template>
      </div>
    </template>

    <el-dialog
        v-model="revisionDetailsVisible"
        title="Client Revision Details"
        width="760px"
        top="8vh"
        append-to-body
        class="fixed-dialog client-revision-details-dialog"
        modal-class="client-revision-details-overlay"
    >
      <div class="fixed-dialog-body client-revision-details-body">
        <div class="client-revision-info">
          <div class="client-revision-info-row">
            <div class="client-revision-info-label">Current Revision</div>
            <div class="client-revision-info-value mono">
              {{ revisionDetails.current_revision || 'unknown' }}
            </div>
          </div>
          <div class="client-revision-info-row">
            <div class="client-revision-info-label">Server Revision</div>
            <div class="client-revision-info-value mono">
              {{ revisionDetails.server_revision || 'unknown' }}
            </div>
          </div>
        </div>

        <div class="client-revision-section-title">Changed Files</div>

        <el-table
            v-if="revisionDetails.changed_files_available && revisionDetails.changed_files.length"
            :data="revisionDetails.changed_files"
            stripe
            border
            size="small"
            max-height="360"
            table-layout="fixed"
            empty-text="No changed files"
        >
          <el-table-column
              prop="change"
              label="Change"
              width="120"
          >
            <template #default="{ row }">
              {{ String(row.change || 'modified').toUpperCase() }}
            </template>
          </el-table-column>
          <el-table-column
              prop="path"
              label="Path"
              min-width="480"
          >
            <template #default="{ row }">
              <span class="client-revision-path mono">{{ row.path }}</span>
            </template>
          </el-table-column>
        </el-table>

        <el-empty
            v-else-if="!revisionDetails.changed_files_available"
            :image-size="64"
            description="File-level details are unavailable for this client build."
        />

        <el-empty
            v-else
            :image-size="64"
            description="No file-level differences were reported."
        />
      </div>
    </el-dialog>
  </div>
</template>

<script>
import { saveCommandOutputArtifact } from '../api/artifactsApi.js'
import {ElMessage} from 'element-plus'
import TerminalLinkedText from './TerminalLinkedText.vue'
import {
  isTerminalCommandFinishedText,
  isTerminalRemoteUploadText,
  TERMINAL_FILE_READY_PREFIX,
  TERMINAL_RUN_SCRIPT_PREFIX,
} from '../composables/terminalMarkers.js'
import { buildTerminalOutputJson, buildTerminalOutputText } from '../utils/terminalOutputExport.js'

export default {
  name: 'TerminalOutput',

  components: {
    TerminalLinkedText,
  },

  props: {
    lines: {
      type: Array,
      default: () => [],
    },

    selectedId: {
      type: [String, Number],
      default: '',
    },

    currentConnection: {
      type: Object,
      default: null,
    },
  },

  emits: ['preview-artifact', 'open-json', 'artifact-saved', 'rerun-terminal-block', 'suggest-command', 'open-task-details'],

  data() {
    return {
      savingOutputBlockKeys: {},
      collapsedTerminalBlockKeys: {},
      revisionDetailsVisible: false,
      revisionDetails: {
        current_revision: '',
        server_revision: '',
        changed_files: [],
        changed_files_available: false,
      },
    }
  },

  computed: {
    terminalBlocks() {
      const safeLines = Array.isArray(this.lines) ? this.lines : []
      const blocks = []
      let currentBlock = null

      safeLines.forEach((line, index) => {
        const entry = {line, index}
        const shouldStartNewBlock =
            !currentBlock ||
            line?.kind === 'command' ||
            this.isCommandFinishedLine(currentBlock.lines[currentBlock.lines.length - 1]?.line)

        if (shouldStartNewBlock) {
          currentBlock = {
            key: `terminal-block-${index}`,
            startIndex: index,
            commandLine: line?.kind === 'command' ? entry : null,
            lines: [],
          }
          blocks.push(currentBlock)
        }

        currentBlock.lines.push(entry)

        if (!currentBlock.commandLine && line?.kind === 'command') {
          currentBlock.commandLine = entry
        }
      })

      return blocks.map(block => {
        const bodyLines = block.lines.filter(entry => entry.index !== block.commandLine?.index)
        const commandText = this.normalizeTerminalBlockCommandText(block.commandLine?.line?.text)
        const blockModel = this.buildTerminalBlockModel({
          ...block,
          bodyLines,
          commandText,
        })

        return {
          ...block,
          ...blockModel,
          bodyLines,
          commandText,
          endIndex: block.lines.length ? block.lines[block.lines.length - 1].index : block.startIndex,
        }
      })
    },
  },

  methods: {

    shouldParseTerminalLineLinks(line) {
      if (!line) return false
      if (line.kind === 'command') return false
      if (this.isCommandFinishedLine(line)) return false
      return true
    },

    hasTerminalBlockOutput(block) {
      return this.getTerminalBlockOutputText(block).trim().length > 0
    },


    isFileReadyLine(line) {
      const text = line?.text || ''
      return text.startsWith(TERMINAL_FILE_READY_PREFIX)
    },

    isCommandFinishedLine(line) {
      return isTerminalCommandFinishedText(line?.text || '')
    },

    getTerminalInlineActionItems(lines, index) {
      const line = lines[index]
      if (!line) return []

      if (!this.isFileReadyLine(line)) return []

      const groupItems = this.getTerminalCommandGroupActionItems(lines, index) || []
      const usedKeysBefore = this.getUsedInlineActionKeysBeforeLine(lines, index)

      const previewItem = groupItems.find(item => {
        return item.type === 'preview' && !usedKeysBefore.has(item.key)
      })

      return previewItem ? [previewItem] : []
    },

    getTerminalTailActionItems(lines, index) {
      const line = lines[index]
      if (!line || !this.isCommandFinishedLine(line)) return []

      const groupItems = this.getTerminalCommandGroupActionItems(lines, index) || []
      const usedKeysUpToCurrent = this.getUsedInlineActionKeysUpToLine(lines, index)

      return groupItems.filter(item => !usedKeysUpToCurrent.has(item.key))
    },

    getUsedInlineActionKeysBeforeLine(lines, endIndexExclusive) {
      const used = new Set()

      for (let i = 0; i < endIndexExclusive; i += 1) {
        const line = lines[i]
        if (!this.isFileReadyLine(line)) continue

        const groupItems = this.getTerminalCommandGroupActionItems(lines, i) || []
        const previewItem = groupItems.find(item => item.type === 'preview' && !used.has(item.key))

        if (previewItem) {
          used.add(previewItem.key)
        }
      }

      return used
    },

    getUsedInlineActionKeysUpToLine(lines, endIndexInclusive) {
      const used = new Set()

      for (let i = 0; i <= endIndexInclusive; i += 1) {
        const line = lines[i]
        if (!this.isFileReadyLine(line)) continue

        const groupItems = this.getTerminalCommandGroupActionItems(lines, i) || []
        const previewItem = groupItems.find(item => item.type === 'preview' && !used.has(item.key))

        if (previewItem) {
          used.add(previewItem.key)
        }
      }

      return used
    },

    getTerminalCommandGroupStartIndex(lines, endIndex) {
      const safeLines = Array.isArray(lines) ? lines : []

      for (let i = endIndex; i >= 0; i -= 1) {
        const line = safeLines[i]
        if (!line) continue

        if (line.kind === 'command') {
          return i
        }

        if (i < endIndex && this.isCommandFinishedLine(line)) {
          return i + 1
        }
      }

      return 0
    },

    getTerminalCommandGroupLines(lines, endIndex) {
      const safeLines = Array.isArray(lines) ? lines : []
      if (!safeLines.length || endIndex < 0) return []

      const startIndex = this.getTerminalCommandGroupStartIndex(safeLines, endIndex)
      return safeLines.slice(startIndex, endIndex + 1)
    },

    getTerminalCommandGroupActionItems(lines, endIndex) {
      const groupLines = this.getTerminalCommandGroupLines(lines, endIndex)
      const commandInfo = this.buildTerminalJsonCommandInfo(groupLines)
      const result = []

      groupLines.forEach((item, itemIndex) => {
        if (!item) return

        if (item.isArtifactMessage && item.artifactInfo && item.artifactInfo.artifact_id) {
          result.push({
            type: 'preview',
            key: `preview:${item.artifactInfo.artifact_id}:${itemIndex}`,
            line: item,
          })
        }

        if (item.isJsonMessage) {
          result.push({
            type: 'json',
            key: `json:${endIndex}:${itemIndex}`,
            line: item,
            commandInfo,
          })
        }
      })

      return result
    },

    getSuggestedCommandAction(line) {
      const command = String(line?.meta?.suggestedCommand || '').trim()
      if (!command) return null

      return {
        command,
        label: String(line?.meta?.suggestedCommandLabel || command).trim() || command,
      }
    },

    handleSuggestedCommandClick(line) {
      const action = this.getSuggestedCommandAction(line)
      if (!action) return
      this.$emit('suggest-command', action.command)
    },

    getClientRevisionDetails(line) {
      const details = line?.meta?.clientRevisionDetails
      if (!details || typeof details !== 'object') return null
      return details
    },

    openClientRevisionDetails(line) {
      const details = this.getClientRevisionDetails(line)
      if (!details) return

      this.revisionDetails = {
        current_revision: String(details.current_revision || '').trim(),
        server_revision: String(details.server_revision || '').trim(),
        changed_files: Array.isArray(details.changed_files)
          ? details.changed_files
              .map(item => ({
                path: String(item?.path || '').trim(),
                change: String(item?.change || 'modified').trim() || 'modified',
              }))
              .filter(item => item.path)
          : [],
        changed_files_available: details.changed_files_available === true,
      }
      this.revisionDetailsVisible = true
    },

    handleTerminalActionClick(actionItem) {
      if (!actionItem || !actionItem.line) return

      if (actionItem.type === 'preview') {
        this.previewTerminalArtifact(actionItem.line)
        return
      }

      if (actionItem.type === 'json') {
        this.$emit('open-json', this.buildTerminalJsonOpenPayload(actionItem))
      }
    },

    buildTerminalJsonOpenPayload(actionItem) {
      const line = actionItem?.line || {}

      return {
        ...line,
        jsonCommandInfo: actionItem?.commandInfo || {},
      }
    },

    buildTerminalJsonCommandInfo(groupLines) {
      const safeLines = Array.isArray(groupLines) ? groupLines : []
      const commandLine = safeLines.find(line => line?.kind === 'command') || null
      const commandText = this.normalizeTerminalBlockCommandText(commandLine?.text || '')
      const entries = safeLines.map(line => ({line}))

      const block = {
        commandLine: commandLine ? {line: commandLine} : null,
        bodyLines: entries,
        lines: entries,
        commandText,
      }

      const blockModel = this.buildTerminalBlockModel(block)
      const commandBlock = {
        ...block,
        ...blockModel,
      }

      const sourceCommandId = this.getTerminalBlockSourceCommandId(commandBlock)
      const isScript = this.isTerminalScriptRunBlock(commandBlock)
      const scriptMeta = commandBlock.scriptMeta || {}
      const commandName = isScript
          ? String(scriptMeta.script_display_name || scriptMeta.script_name || commandText).trim()
          : commandText

      return {
        blockType: commandBlock.blockType || (isScript ? 'script' : 'command'),
        commandText,
        commandId: sourceCommandId,
        taskId: commandBlock.taskId || '',

        command_id: sourceCommandId,
        source_command_id: sourceCommandId,
        command_name: commandName,
        name: commandName,
        source_command: commandName,
        source_task_id: commandBlock.taskId || '',
        category: this.getTerminalBlockArtifactCategory(commandBlock),
        is_script: isScript,

        script_name: scriptMeta.script_name || '',
        script_path: scriptMeta.script_path || '',
        script_display_name: scriptMeta.script_display_name || '',
        params: scriptMeta.params || {},

        scriptMeta: {
          script_name: scriptMeta.script_name || '',
          script_path: scriptMeta.script_path || '',
          script_display_name: scriptMeta.script_display_name || '',
          params: scriptMeta.params || {},
        },
      }
    },

    previewTerminalArtifact(line) {
      if (!line || !line.artifactInfo || !line.artifactInfo.artifact_id) {
        ElMessage.warning('No preview available')
        return
      }

      this.$emit('preview-artifact', line.artifactInfo)
    },

    scrollToBottom() {
      this.$nextTick(() => {
        const el = this.$refs.terminalOutputRef
        const isMobileLayout =
            typeof window !== 'undefined' &&
            window.matchMedia &&
            window.matchMedia('(max-width: 960px)').matches

        if (isMobileLayout) {
          const appScrollRoot = document.getElementById('app')
          const scrollRoot = appScrollRoot || document.scrollingElement || document.documentElement

          if (scrollRoot) {
            scrollRoot.scrollTop = scrollRoot.scrollHeight
          } else if (typeof window !== 'undefined') {
            window.scrollTo(0, document.documentElement.scrollHeight)
          }

          return
        }

        if (el) {
          el.scrollTop = el.scrollHeight
        }
      })
    },

    // terminal block

    normalizeTerminalBlockCommandText(text) {
      const raw = String(text || '').trim()
      return raw.replace(/^>\s*/, '').trim()
    },

    getTerminalBlockCommandText(block) {
      return String(block?.commandText || this.normalizeTerminalBlockCommandText(block?.commandLine?.line?.text)).trim()
    },

    normalizeTerminalOutputLineText(text) {
      const value = String(text ?? '')
      return value === ' ' ? '' : value
    },

    getTerminalLineMeta(line) {
      return line?.meta && typeof line.meta === 'object' ? line.meta : {}
    },

    getTerminalEntryMeta(entry) {
      return this.getTerminalLineMeta(entry?.line)
    },

    getTerminalBlockMetaList(block) {
      const entries = []
      if (block?.commandLine) entries.push(block.commandLine)
      if (Array.isArray(block?.bodyLines)) entries.push(...block.bodyLines)
      if (Array.isArray(block?.lines)) entries.push(...block.lines)

      const result = []
      entries.forEach(entry => {
        const meta = this.getTerminalEntryMeta(entry)
        if (Object.keys(meta).length > 0) result.push(meta)

        const nested = meta.metadata && typeof meta.metadata === 'object' ? meta.metadata : null
        if (nested && Object.keys(nested).length > 0) result.push(nested)
      })
      return result
    },

    findTerminalBlockMetaValue(block, keys) {
      const metaList = this.getTerminalBlockMetaList(block)
      for (const meta of metaList) {
        for (const key of keys) {
          if (meta[key] !== undefined && meta[key] !== null && String(meta[key]).trim() !== '') {
            return meta[key]
          }
        }
      }
      return null
    },

    normalizeNullableInt(value) {
      if (value === null || value === undefined || value === '') return null
      const numberValue = Number(value)
      return Number.isFinite(numberValue) ? numberValue : value
    },

    buildTerminalBlockScriptMeta(block) {
      const paramsValue = this.findTerminalBlockMetaValue(block, ['params', 'script_params'])
      const params = paramsValue && typeof paramsValue === 'object' && !Array.isArray(paramsValue)
          ? {...paramsValue}
          : {}

      return {
        script_name: String(this.findTerminalBlockMetaValue(block, ['script_name']) || '').trim(),
        script_path: String(this.findTerminalBlockMetaValue(block, ['script_path', 'path']) || '').trim(),
        script_display_name: String(this.findTerminalBlockMetaValue(block, ['script_display_name', 'display_name']) || '').trim(),
        params,
      }
    },

    buildTerminalBlockModel(block) {
      const commandText = this.getTerminalBlockCommandText(block)
      const terminalBlockType = String(this.findTerminalBlockMetaValue(block, ['terminal_block_type', 'terminalBlockType']) || '').trim()
      const scriptMeta = this.buildTerminalBlockScriptMeta(block)
      const isScript = terminalBlockType === 'script' || !!scriptMeta.script_name || commandText.toLowerCase().startsWith(TERMINAL_RUN_SCRIPT_PREFIX.toLowerCase())
      const isRemoteUpload = isTerminalRemoteUploadText(commandText)

      return {
        blockType: isScript ? 'script' : (isRemoteUpload ? 'remote_upload' : 'command'),
        commandId: this.normalizeNullableInt(this.findTerminalBlockMetaValue(block, ['command_id', 'source_command_id'])),
        taskId: String(this.findTerminalBlockMetaValue(block, ['task_id']) || '').trim(),
        scriptMeta,
      }
    },

    isTerminalScriptRunBlock(block) {
      return String(block?.blockType || '').trim() === 'script'
    },

    isTerminalRemoteUploadBlock(block) {
      if (String(block?.blockType || '').trim() === 'remote_upload') {
        return true
      }

      return isTerminalRemoteUploadText(this.getTerminalBlockCommandText(block))
    },

    getTerminalBlockArtifactCategory(block) {
      return this.isTerminalScriptRunBlock(block)
          ? 'script_output'
          : 'command_output'
    },

    getTerminalBlockSourceCommandId(block) {
      return block?.commandId ?? this.normalizeNullableInt(this.findTerminalBlockMetaValue(block, ['command_id', 'source_command_id']))
    },

    getTerminalBlockOutputLineEntries(block) {
      const entries = Array.isArray(block?.bodyLines) ? block.bodyLines : []

      return entries.filter(entry => {
        const line = entry?.line
        if (!line) return false
        if (line.kind === 'command') return false
        if (this.isCommandFinishedLine(line)) return false
        return true
      })
    },

    getTerminalBlockOutputText(block) {
      return this.getTerminalBlockOutputLineEntries(block)
          .map(entry => this.normalizeTerminalOutputLineText(entry.line?.text))
          .join('\n')
    },

    canUseTerminalBlockActions(block) {
      if (!block || !block.commandLine) return false
      return this.getTerminalBlockOutputText(block).trim().length > 0
    },

    getTerminalBlockKey(block) {
      return String(block?.key || '')
    },

    getTerminalBlockCollapseKey(block) {
      const key = this.getTerminalBlockKey(block)
      if (!key) return ''

      return `${key}:${String(block?.endIndex ?? '')}:${this.getTerminalBlockCommandText(block)}`
    },

    isTerminalBlockCollapsed(block) {
      const key = this.getTerminalBlockCollapseKey(block)
      return !!(key && this.collapsedTerminalBlockKeys[key])
    },

    setTerminalBlockCollapsed(block, value) {
      const key = this.getTerminalBlockCollapseKey(block)
      if (!key) return

      if (!value) {
        const next = {...this.collapsedTerminalBlockKeys}
        delete next[key]
        this.collapsedTerminalBlockKeys = next
        return
      }

      this.collapsedTerminalBlockKeys = {
        ...this.collapsedTerminalBlockKeys,
        [key]: true,
      }
    },

    toggleTerminalBlockCollapsed(block) {
      this.setTerminalBlockCollapsed(block, !this.isTerminalBlockCollapsed(block))
    },

    getVisibleTerminalBlockBodyLines(block) {
      const bodyLines = Array.isArray(block?.bodyLines) ? block.bodyLines : []

      if (!this.isTerminalBlockCollapsed(block)) {
        return bodyLines
      }

      return bodyLines.filter(entry => this.isCommandFinishedLine(entry?.line))
    },

    isSavingTerminalBlock(block) {
      const key = this.getTerminalBlockKey(block)
      return !!(key && this.savingOutputBlockKeys[key])
    },

    setTerminalBlockSaving(block, value) {
      const key = this.getTerminalBlockKey(block)
      if (!key) return

      this.savingOutputBlockKeys = {
        ...this.savingOutputBlockKeys,
        [key]: !!value,
      }
    },

    handleTerminalBlockCommand(block, command) {
      const normalizedCommand = String(command || '').trim()

      if (normalizedCommand === 'toggle-collapse') {
        this.toggleTerminalBlockCollapsed(block)
        return
      }

      if (normalizedCommand === 'copy-command') {
        this.copyTerminalBlockCommand(block)
        return
      }

      if (normalizedCommand === 'rerun-command') {
        this.rerunTerminalBlock(block)
        return
      }

      if (normalizedCommand === 'copy-output') {
        this.copyTerminalBlockOutput(block)
        return
      }

      if (normalizedCommand === 'save-output') {
        this.saveTerminalBlockOutput(block)
      }
    },

    copyTerminalBlockCommand(block) {
      if (this.isTerminalRemoteUploadBlock(block)) {
        ElMessage.warning('Remote upload is not a reusable command')
        return
      }

      if (this.isTerminalScriptRunBlock(block)) {
        ElMessage.warning('Script command copy is disabled')
        return
      }

      const commandText = this.getTerminalBlockCommandText(block)

      if (!commandText) {
        ElMessage.warning('No command to copy')
        return
      }

      this.copyTextToClipboard(commandText)
          .then(() => {
            ElMessage.success('Command copied')
          })
          .catch(e => {
            ElMessage.error(e.message || 'Copy failed')
          })
    },

    rerunTerminalBlock(block) {
      if (this.isTerminalRemoteUploadBlock(block)) {
        ElMessage.warning('Remote upload cannot be run again from terminal history')
        return
      }

      const isScript = this.isTerminalScriptRunBlock(block)
      const commandText = this.getTerminalBlockCommandText(block)
      const scriptMeta = block?.scriptMeta || this.buildTerminalBlockScriptMeta(block)

      if (!isScript && !commandText) {
        ElMessage.warning('No command to run')
        return
      }

      if (isScript && !String(scriptMeta.script_name || '').trim()) {
        ElMessage.warning('Missing script name')
        return
      }

      this.$emit('rerun-terminal-block', {
        type: isScript ? 'script' : 'command',
        command: isScript ? '' : commandText,
        script_name: scriptMeta.script_name || '',
        script_path: scriptMeta.script_path || '',
        script_display_name: scriptMeta.script_display_name || '',
        params: scriptMeta.params || {},
      })
    },

    async copyTerminalBlockOutput(block) {
      const outputText = this.getTerminalBlockOutputText(block)

      if (!outputText.trim()) {
        ElMessage.warning('No output to copy')
        return
      }

      try {
        await this.copyTextToClipboard(outputText)
        ElMessage.success('Output copied')
      } catch (e) {
        ElMessage.error(e.message || 'Copy failed')
      }
    },

    async copyTextToClipboard(text) {
      if (
          typeof navigator !== 'undefined' &&
          navigator.clipboard &&
          typeof navigator.clipboard.writeText === 'function'
      ) {
        await navigator.clipboard.writeText(text)
        return
      }

      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.setAttribute('readonly', 'readonly')
      textarea.style.position = 'fixed'
      textarea.style.left = '-9999px'
      textarea.style.top = '-9999px'
      document.body.appendChild(textarea)
      textarea.select()

      const ok = document.execCommand('copy')
      document.body.removeChild(textarea)

      if (!ok) {
        throw new Error('Copy failed')
      }
    },

    buildTerminalToolbarJsonEntries() {
      return buildTerminalOutputJson(this.terminalBlocks.map(block => ({
        hasCommand: Boolean(block.commandLine),
        command: this.getTerminalBlockCommandText(block),
        result: this.getTerminalBlockOutputText(block),
        time: this.findTerminalBlockMetaValue(block, ['started_at', 'created_at', 'timestamp', 'finished_at']),
        duration_ms: this.normalizeNullableInt(
          this.findTerminalBlockMetaValue(block, ['duration_ms', 'elapsed_ms', 'execution_duration_ms']),
        ),
      })))
    },

    getTerminalToolbarOutput(format = 'text') {
      if (String(format || '').trim().toLowerCase() === 'json') {
        const entries = this.buildTerminalToolbarJsonEntries()
        return { content: JSON.stringify(entries, null, 2), format: 'json', commandCount: entries.length }
      }
      return {
        content: buildTerminalOutputText(this.lines.map(line => ({
          text: this.normalizeTerminalOutputLineText(line?.text),
        }))),
        format: 'text',
        commandCount: this.terminalBlocks.filter(block => block.commandLine).length,
      }
    },

    async copyAllTerminalOutput(format = 'text') {
      const output = this.getTerminalToolbarOutput(format)
      if (!output.content.trim() || (output.format === 'json' && output.commandCount === 0)) {
        ElMessage.warning(output.format === 'json' ? 'No command output to copy' : 'No terminal output to copy')
        return
      }

      try {
        await this.copyTextToClipboard(output.content)
        ElMessage.success(output.format === 'json' ? 'Terminal JSON copied' : 'Terminal output copied')
      } catch (error) {
        ElMessage.error(error.message || 'Copy failed')
      }
    },

    async saveAllTerminalOutputArtifact(format = 'text') {
      const output = this.getTerminalToolbarOutput(format)
      if (!output.content.trim() || (output.format === 'json' && output.commandCount === 0)) {
        ElMessage.warning(output.format === 'json' ? 'No command output to save' : 'No terminal output to save')
        return
      }

      try {
        await this.saveTerminalOutputArtifactBody({
          content: output.content,
          artifact_type: 'command_output',
          category: 'command_output',
          client_id: String(this.selectedId || ''),
          hostname: String(this.currentConnection?.hostname || ''),
          machine_id: String(this.currentConnection?.machine_id || ''),
          source: 'terminal_toolbar_action',
          source_command: '',
          source_command_id: null,
          output_format: output.format,
          extra: {
            saved_from: 'terminal_toolbar',
            output_format: output.format,
          },
        })
      } catch (error) {
        ElMessage.error(error.message || 'Save failed')
      }
    },

    buildTerminalOutputFilename(block) {
      const now = new Date()
      const pad = value => String(value).padStart(2, '0')
      const timestamp = [
        now.getFullYear(),
        pad(now.getMonth() + 1),
        pad(now.getDate()),
      ].join('') + '_' + [
        pad(now.getHours()),
        pad(now.getMinutes()),
        pad(now.getSeconds()),
      ].join('')

      const prefix = this.isTerminalScriptRunBlock(block) ? 'script' : 'cmd'
      return `${prefix}_${timestamp}.txt`
    },


    buildTerminalOutputArtifactExtra(block, options = {}) {
      const sourceCommandId = this.getTerminalBlockSourceCommandId(block)
      const isScript = this.isTerminalScriptRunBlock(block)

      const artifactSource = String(options.source || '').trim()
          || (isScript ? 'script_terminal_inline_action' : 'terminal_inline_action')

      const savedFrom = String(options.savedFrom || '').trim() || 'terminal_output'

      const baseExtra = {
        source: artifactSource,
        wrapper_command: '',
        source_history_entry_id: '',
        source_task_id: block?.taskId || '',
        source_command_id: sourceCommandId,
        saved_from: savedFrom,
        category: this.getTerminalBlockArtifactCategory(block),
        saved_at: new Date().toISOString(),
      }

      if (!isScript) {
        baseExtra.source_command = this.getTerminalBlockCommandText(block)
        return baseExtra
      }

      const scriptMeta = block?.scriptMeta || this.buildTerminalBlockScriptMeta(block)

      return {
        ...baseExtra,
        script_name: scriptMeta.script_name || '',
        script_path: scriptMeta.script_path || '',
        script_display_name: scriptMeta.script_display_name || '',
        params: scriptMeta.params || {},
      }
    },


    buildTerminalOutputArtifactSaveBody(block, content, options = {}) {
      const commandText = this.getTerminalBlockCommandText(block)
      const artifactCategory = this.getTerminalBlockArtifactCategory(block)
      const sourceCommandId = this.getTerminalBlockSourceCommandId(block)
      const isScript = this.isTerminalScriptRunBlock(block)

      const source = String(options.source || '').trim()
          || (isScript ? 'script_terminal_inline_action' : 'terminal_inline_action')

      return {
        content,
        artifact_type: 'command_output',
        category: artifactCategory,
        client_id: String(this.selectedId || ''),
        hostname: String(this.currentConnection?.hostname || ''),
        machine_id: String(this.currentConnection?.machine_id || ''),
        source,
        source_command: isScript ? '' : commandText,
        source_command_id: sourceCommandId,
        extra: this.buildTerminalOutputArtifactExtra(block, options),
      }
    },

    async saveTerminalOutputArtifactBody(body) {
      const res = await saveCommandOutputArtifact(body)

      const json = await res.json()
      if (!res.ok || json.code !== 0) {
        throw new Error(json.message || 'Save failed')
      }

      ElMessage.success('Saved to Command Output')
      this.$emit('artifact-saved', json.data || null)
      return json.data || null
    },

    normalizeTerminalJsonSaveBlock(saveContext) {
      const context = saveContext && typeof saveContext === 'object' ? saveContext : {}
      const directScriptMeta = context.scriptMeta && typeof context.scriptMeta === 'object'
          ? context.scriptMeta
          : {}

      const fallbackScriptMeta = {
        script_name: context.script_name || '',
        script_path: context.script_path || '',
        script_display_name: context.script_display_name || '',
        params: context.params || {},
      }

      const scriptMeta = Object.keys(directScriptMeta).length ? directScriptMeta : fallbackScriptMeta
      const isScript = !!context.is_script || String(context.blockType || '').trim() === 'script'

      return {
        key: `terminal-json-viewer-save-${Date.now()}`,
        commandText: String(
            context.commandText
            || context.source_command
            || context.command_name
            || context.name
            || ''
        ).trim(),
        blockType: isScript ? 'script' : (String(context.blockType || '').trim() || 'command'),
        commandId: this.normalizeNullableInt(
            context.commandId
            ?? context.command_id
            ?? context.source_command_id
        ),
        taskId: String(context.taskId || context.source_task_id || context.task_id || '').trim(),
        scriptMeta: {
          script_name: String(scriptMeta.script_name || '').trim(),
          script_path: String(scriptMeta.script_path || '').trim(),
          script_display_name: String(scriptMeta.script_display_name || '').trim(),
          params: scriptMeta.params && typeof scriptMeta.params === 'object' && !Array.isArray(scriptMeta.params)
              ? {...scriptMeta.params}
              : {},
        },
        commandLine: null,
        bodyLines: [],
        lines: [],
      }
    },
    async saveTerminalJsonOutputFromViewer(payload = {}) {
      const content = String(payload.content || '')
      const done = typeof payload.onDone === 'function' ? payload.onDone : null

      try {
        if (!content.trim()) {
          ElMessage.warning('No output to save')
          return
        }

        const block = this.normalizeTerminalJsonSaveBlock(payload.saveContext)

        const body = this.buildTerminalOutputArtifactSaveBody(block, content, {
          source: 'terminal_json_viewer_action',
          savedFrom: 'terminal_json_viewer',
        })

        await this.saveTerminalOutputArtifactBody(body)
      } catch (e) {
        ElMessage.error(e.message || 'Save failed')
      } finally {
        if (done) done()
      }
    },


    // buildTerminalOutputArtifactExtra(block) {
    //   const outputEntries = this.getTerminalBlockOutputLineEntries(block)
    //   const sourceCommandId = this.getTerminalBlockSourceCommandId(block)
    //   const isScript = this.isTerminalScriptRunBlock(block)
    //   const baseExtra = {
    //     source: isScript ? 'script_terminal_inline_action' : 'terminal_inline_action',
    //     wrapper_command: '',
    //     source_history_entry_id: '',
    //     source_task_id: block?.taskId || '',
    //     source_command_id: sourceCommandId,
    //     saved_from: 'terminal_output',
    //     category: this.getTerminalBlockArtifactCategory(block),
    //     line_count: outputEntries.length,
    //     saved_at: new Date().toISOString(),
    //   }
    //
    //   if (!isScript) {
    //     baseExtra.source_command = this.getTerminalBlockCommandText(block)
    //     return baseExtra
    //   }
    //
    //   const scriptMeta = block?.scriptMeta || this.buildTerminalBlockScriptMeta(block)
    //   return {
    //     ...baseExtra,
    //     script_name: scriptMeta.script_name || '',
    //     script_path: scriptMeta.script_path || '',
    //     script_display_name: scriptMeta.script_display_name || '',
    //     params: scriptMeta.params || {},
    //   }
    // },

    async saveTerminalBlockOutput(block) {
      if (this.isSavingTerminalBlock(block)) return

      const outputText = this.getTerminalBlockOutputText(block)
      if (!outputText.trim()) {
        ElMessage.warning('No output to save')
        return
      }

      this.setTerminalBlockSaving(block, true)

      try {
        const body = this.buildTerminalOutputArtifactSaveBody(block, outputText)
        await this.saveTerminalOutputArtifactBody(body)
      } catch (e) {
        ElMessage.error(e.message || 'Save failed')
      } finally {
        this.setTerminalBlockSaving(block, false)
      }
    },
  },
}
</script>

<style scoped>
/* ========== 终端输出区 ========== */
.terminal-output {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 18px 18px 22px;
  color: var(--terminal-text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.7;
  scrollbar-width: thin;
  scrollbar-color: rgba(148, 163, 184, 0.35) rgba(15, 23, 42, 0.4);
}

.terminal-output::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

.terminal-output::-webkit-scrollbar-track {
  background: rgba(15, 23, 42, 0.45);
}

.terminal-output::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.32);
  border-radius: 999px;
  border: 2px solid rgba(15, 23, 42, 0.45);
}

.terminal-output::-webkit-scrollbar-thumb:hover {
  background: rgba(148, 163, 184, 0.48);
}

.terminal-empty {
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  color: #8ea2c0;
  text-align: center;
}

.terminal-empty-title {
  font-size: 15px;
  font-weight: 700;
  color: #d7e2f2;
}

.terminal-empty-text {
  margin-top: 8px;
  max-width: 420px;
  line-height: 1.7;
}

.terminal-line {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  white-space: pre-wrap;
  word-break: break-word;
  padding: 1px 0;
}


.terminal-action-link-spaced {
  margin-left: 10px;
}

.terminal-prefix {
  color: #60a5fa;
  font-weight: 700;
  flex-shrink: 0;
}

.terminal-text {
  min-width: 0;
}

.line-command .terminal-text {
  color: #bfdbfe;
}
/*
.line-success .terminal-text {
  color: #86efac;
}

.line-error .terminal-text {
  color: #fda4af;
}

.line-info .terminal-text {
  color: #fcd34d;
}

.line-default .terminal-text {
  color: var(--terminal-text);
}
*/

.line-success .terminal-text {
  color: #86efac;
}

.line-error .terminal-text {
  color: #fda4af;
}

.line-warning .terminal-text {
  color: #fcd34d;
}

.line-info .terminal-text {
  color: #93c5fd;
}

.line-default .terminal-text {
  color: var(--terminal-text);
}

.client-revision-details-body {
  display: flex;
  flex-direction: column;
  gap: 18px;
  max-height: 72vh;
  overflow: auto;
}

.client-revision-info {
  border-top: 1px solid #ebeef5;
}

.client-revision-info-row {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 12px;
  padding: 9px 0;
  border-bottom: 1px solid #ebeef5;
}

.client-revision-info-label {
  color: #606266;
  font-weight: 500;
}

.client-revision-info-value {
  min-width: 0;
  color: #303133;
  word-break: break-word;
}

.client-revision-section-title {
  color: #303133;
  font-weight: 600;
}

.client-revision-path {
  word-break: break-all;
}

:global(.client-revision-details-overlay .el-overlay-dialog) {
  overflow: auto;
}

@media (max-width: 768px) {
  /* Warning action links follow the warning text rather than squeezing it. */
  .terminal-warning-with-actions { display: block; overflow-wrap: anywhere; }
  .terminal-warning-with-actions .terminal-action-link-spaced {
    display: inline-block;
    white-space: nowrap;
  }
  .client-revision-info-row {
    grid-template-columns: 118px minmax(0, 1fr);
  }

  :global(.client-revision-details-overlay .el-dialog) {
    width: calc(100vw - 24px) !important;
    max-width: calc(100vw - 24px) !important;
    margin-top: 4vh !important;
  }
}

@media (max-width: 960px) {
  .terminal-output {
    min-height: 340px;
  }

  .terminal-output.terminal-output-empty .terminal-empty {
    min-height: 340px;
  }
}

/*terminal block*/
.terminal-command-block {
  position: relative;
  border-radius: 8px;
  margin: 0 -6px 2px;
  padding: 0 6px;
}

.terminal-command-block-actionable:hover {
  background: rgba(15, 23, 42, 0.16);
}

.terminal-block-command-row {
  display: flex;
  align-items: flex-start;
  min-width: 0;
}

.terminal-block-command-row .terminal-line {
  min-width: 0;
}

.terminal-command-finished-row {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.terminal-command-finished-row .terminal-text {
  flex: 0 1 auto;
  min-width: 0;
}

.terminal-block-collapsed-badge {
  flex: 0 0 auto;
  padding: 0 6px;
  border: 1px solid rgba(148, 163, 184, 0.36);
  border-radius: 999px;
  color: rgba(203, 213, 225, 0.72);
  font-size: 11px;
  line-height: 16px;
}

.terminal-block-more {
  position: relative;
  flex: 0 0 auto;
  width: 18px;
  height: 18px;
  padding: 0;
  margin: 0 0 0 2px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: rgba(203, 213, 225, 0.46);
  cursor: pointer;
  opacity: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  font-size: 0;
  font-family: inherit;
  vertical-align: middle;
  transform: translateY(1px);
  transition: opacity 0.12s ease,
  background 0.12s ease,
  color 0.12s ease,
  border-color 0.12s ease;
}

.terminal-block-more::before {
  content: '';
  position: absolute;
  left: 50%;
  top: 50%;
  width: 2px;
  height: 2px;
  border-radius: 999px;
  background: currentColor;
  transform: translate(-50%, -50%);
  box-shadow: -4px 0 0 currentColor,
  4px 0 0 currentColor;
}

.terminal-command-block:hover .terminal-block-more,
.terminal-block-more:focus-visible,
.terminal-block-more[aria-expanded='true'] {
  opacity: 1;
}

.terminal-block-more:hover,
.terminal-block-more:focus-visible,
.terminal-block-more[aria-expanded='true'] {
  background: rgba(148, 163, 184, 0.10);
  border-color: rgba(148, 163, 184, 0.18);
  border-radius: 999px;
  color: rgba(226, 232, 240, 0.78);
  outline: none;
}

:global(.terminal-output-action-dropdown .el-dropdown-menu__item) {
  font-size: 12px;
  padding: 0 13px;
}
</style>