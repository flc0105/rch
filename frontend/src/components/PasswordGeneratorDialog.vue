<template>
  <el-dialog
    v-model="visible"
    title="Generate Password"
    width="560px"
    top="8vh"
    append-to-body
    class="password-generator-dialog"
    modal-class="password-generator-overlay"
    @closed="handleClosed"
  >
    <div class="password-generator">
      <div
        class="password-generator-mode-tabs"
        role="tablist"
      >
        <button
          type="button"
          class="mode-tab"
          :class="{ active: generatorMode === 'normal' }"
          @click="setGeneratorMode('normal')"
        >
          <KeyRound class="dialog-action-icon" :size="14" aria-hidden="true" />
          Normal Password
        </button>
        <button
          type="button"
          class="mode-tab"
          :class="{ active: generatorMode === 'apple' }"
          @click="setGeneratorMode('apple')"
        >
          <ShieldCheck class="dialog-action-icon" :size="14" aria-hidden="true" />
          Apple-style Strong Password
        </button>
      </div>

      <div
        v-if="generatorMode === 'normal'"
        class="password-generator-section"
      >
        <el-form
          label-position="top"
          class="password-generator-form"
        >
          <el-form-item label="Password Length">
            <div class="password-length-row">
              <div class="password-length-slider">
                <el-slider
                  v-model="normalOptions.length"
                  :min="6"
                  :max="18"
                  :step="1"
                  show-stops
                  @change="generatePassword"
                />
              </div>
              <el-input-number
                v-model="normalOptions.length"
                :min="6"
                :max="18"
                size="small"
                controls-position="right"
                @change="generatePassword"
              />
            </div>
          </el-form-item>

          <el-form-item label="Character Types">
            <div class="password-option-grid">
              <el-checkbox
                v-model="normalOptions.uppercase"
                @change="generatePassword"
              >
                Uppercase letters
              </el-checkbox>
              <el-checkbox
                v-model="normalOptions.lowercase"
                @change="generatePassword"
              >
                Lowercase letters
              </el-checkbox>
              <el-checkbox
                v-model="normalOptions.numbers"
                @change="generatePassword"
              >
                Numbers
              </el-checkbox>
              <el-checkbox
                v-model="normalOptions.symbols"
                @change="generatePassword"
              >
                Symbols
              </el-checkbox>
            </div>
          </el-form-item>
        </el-form>
      </div>

      <div
        v-else
        class="password-generator-section apple-password-note"
      >
        <div class="apple-password-title">Apple-style Strong Password</div>
        <div class="apple-password-desc">
Generates a 20-character, Apple-style password with CVC syllable chunks, two hyphens, one digit, and one uppercase letter.        </div>
      </div>

      <div class="password-result-card">
        <div class="password-result-label"><KeyRound class="dialog-action-icon" :size="13" aria-hidden="true" />Generated Password</div>
        <div class="password-result-row">
          <div class="password-result-value mono">
            {{ generatedPassword || '-' }}
          </div>
          <el-button
            size="small"
            type="primary"
            plain
            :disabled="!generatedPassword"
            @click="copyGeneratedPassword"
          >
            <Copy class="dialog-action-icon" :size="14" aria-hidden="true" />
            Copy
          </el-button>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="password-generator-footer">
        <el-button @click="visible = false">
          <X class="dialog-action-icon" :size="14" aria-hidden="true" />
          Close
        </el-button>
        <el-button
          v-if="allowApply"
          type="primary"
          plain
          :disabled="!generatedPassword"
          @click="applyGeneratedPassword(false)"
        ><Check class="dialog-action-icon" :size="14" aria-hidden="true" /> Use Password</el-button>
        <el-button
          v-if="allowApply"
          type="primary"
          :disabled="!generatedPassword"
          @click="applyGeneratedPassword(true)"
        ><Save class="dialog-action-icon" :size="14" aria-hidden="true" /> Use & Save</el-button>
        <el-button
          type="primary"
          @click="generatePassword"
        >
          <RefreshCw class="dialog-action-icon" :size="14" aria-hidden="true" />
          {{ generatedPassword ? 'Regenerate' : 'Generate' }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script>
import { Check, Copy, KeyRound, RefreshCw, Save, ShieldCheck, X } from '@lucide/vue'
import { ElMessage } from 'element-plus'

const UPPERCASE_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
const LOWERCASE_CHARS = 'abcdefghijklmnopqrstuvwxyz'
const NUMBER_CHARS = '0123456789'
const SYMBOL_CHARS = '!@#$%^&*()-_=+[]{};:,.?'
const APPLE_STYLE_CONSONANTS = 'bcdfghjklmnpqrstvwz'
const APPLE_STYLE_VOWELS = 'aeiouy'
const APPLE_STYLE_DIGIT_POSITIONS = [5, 6, 11, 12, 17]

export default {
  name: 'PasswordGeneratorDialog',

  components: {
    Check, Copy, KeyRound, RefreshCw, Save, ShieldCheck, X,
  },
  props: { allowApply: { type: Boolean, default: false } },
  emits: ['apply', 'apply-save'],

  data() {
    return {
      visible: false,
      generatorMode: 'normal',
      generatedPassword: '',
      normalOptions: {
        length: 12,
        uppercase: true,
        lowercase: true,
        numbers: true,
        symbols: false,
      },
    }
  },

  methods: {
    open() {
      this.visible = true
      this.generatePassword()
    },

    handleClosed() {
      this.generatedPassword = ''
    },

    applyGeneratedPassword(save) {
      if (!this.allowApply || !this.generatedPassword) return
      this.$emit(save ? 'apply-save' : 'apply', this.generatedPassword)
      this.visible = false
    },

    setGeneratorMode(mode) {
      if (this.generatorMode === mode) return
      this.generatorMode = mode
      this.generatePassword()
    },

    getRandomInt(max) {
      if (!max || max <= 0) return 0

      const cryptoObj = window.crypto || window.msCrypto
      if (!cryptoObj?.getRandomValues) {
        return Math.floor(Math.random() * max)
      }

      const range = 0x100000000
      const limit = range - (range % max)
      const randomValues = new Uint32Array(1)

      do {
        cryptoObj.getRandomValues(randomValues)
      } while (randomValues[0] >= limit)

      return randomValues[0] % max
    },

    getRandomChar(chars) {
      if (!chars) return ''
      return chars[this.getRandomInt(chars.length)]
    },

    shuffleChars(chars) {
      const result = [...chars]
      for (let i = result.length - 1; i > 0; i -= 1) {
        const j = this.getRandomInt(i + 1)
        ;[result[i], result[j]] = [result[j], result[i]]
      }
      return result.join('')
    },

    getSelectedCharSets() {
      const sets = []
      if (this.normalOptions.uppercase) sets.push(UPPERCASE_CHARS)
      if (this.normalOptions.lowercase) sets.push(LOWERCASE_CHARS)
      if (this.normalOptions.numbers) sets.push(NUMBER_CHARS)
      if (this.normalOptions.symbols) sets.push(SYMBOL_CHARS)
      return sets
    },

    generateNormalPassword() {
      const selectedSets = this.getSelectedCharSets()
      if (!selectedSets.length) {
        this.generatedPassword = ''
        ElMessage.warning('Please select at least one character type')
        return
      }

      const length = Math.min(18, Math.max(6, Number(this.normalOptions.length) || 12))
      this.normalOptions.length = length

      // 先确保每个已选字符类型至少出现一次，再随机补足剩余长度。
      const chars = selectedSets.map(set => this.getRandomChar(set))
      const allChars = selectedSets.join('')
      while (chars.length < length) {
        chars.push(this.getRandomChar(allChars))
      }

      this.generatedPassword = this.shuffleChars(chars)
    },

   buildAppleStyleLetters() {
  let letters = ''
  for (let i = 0; i < 18; i += 1) {
    const source = i % 3 === 1 ? APPLE_STYLE_VOWELS : APPLE_STYLE_CONSONANTS
    letters += this.getRandomChar(source)
  }
  return letters.split('')
},

generateAppleStylePassword() {
  const chars = this.buildAppleStyleLetters()
  const digitIndex = APPLE_STYLE_DIGIT_POSITIONS[this.getRandomInt(APPLE_STYLE_DIGIT_POSITIONS.length)]
  chars[digitIndex] = this.getRandomChar(NUMBER_CHARS)

  // Apple-style 密码只放 1 个数字；数字位置随机落在连字符两侧或结尾。
  const uppercaseCandidates = chars
    .map((char, index) => ({ char, index }))
    .filter(item => item.index !== digitIndex && /[a-z]/.test(item.char))
  const uppercaseIndex = uppercaseCandidates[this.getRandomInt(uppercaseCandidates.length)].index
  chars[uppercaseIndex] = chars[uppercaseIndex].toUpperCase()

  this.generatedPassword = `${chars.slice(0, 6).join('')}-${chars.slice(6, 12).join('')}-${chars.slice(12).join('')}`
},

    generatePassword() {
      if (this.generatorMode === 'apple') {
        this.generateAppleStylePassword()
        return
      }

      this.generateNormalPassword()
    },

    async copyGeneratedPassword() {
      if (!this.generatedPassword) return

      try {
        if (
          window.isSecureContext &&
          navigator.clipboard &&
          typeof navigator.clipboard.writeText === 'function'
        ) {
          await navigator.clipboard.writeText(this.generatedPassword)
        } else {
          const textarea = document.createElement('textarea')
          textarea.value = this.generatedPassword
          textarea.setAttribute('readonly', '')
          textarea.style.position = 'fixed'
          textarea.style.opacity = '0'
          document.body.appendChild(textarea)
          textarea.select()
          document.execCommand('copy')
          document.body.removeChild(textarea)
        }

        ElMessage.success('Password copied')
      } catch (e) {
        ElMessage.error(e.message || 'Copy failed')
      }
    },
  },
}
</script>

<style scoped>
.dialog-action-icon {
  flex: 0 0 auto;
  vertical-align: middle;
  margin-right: 4px;
}

.password-generator {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.password-generator-mode-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
  padding: 4px;
  border-radius: 14px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: #f8fafc;
}

.mode-tab {
  border: 0;
  border-radius: 10px;
  padding: 10px 14px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.35;
  transition: background 0.15s ease, box-shadow 0.15s ease, color 0.15s ease;
}

.mode-tab:hover {
  color: var(--text);
}

.mode-tab.active {
  color: var(--text);
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}

.password-generator-section {
  padding: 14px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 14px;
  background: #fff;
}

.password-generator-form :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}

.password-length-row {
  display: flex;
  align-items: center;
  gap: 16px;
  width: 100%;
}

.password-length-slider {
  flex: 1 1 auto;
  min-width: 220px;
  padding: 0 6px;
}

.password-length-row :deep(.el-slider) {
  width: 100%;
}

.password-length-row :deep(.el-input-number) {
  flex: 0 0 112px;
  width: 112px;
}

.password-option-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 14px;
  width: 100%;
}

.password-option-grid :deep(.el-checkbox) {
  margin-right: 0;
}

.apple-password-note {
  background: #f8fafc;
}

.apple-password-title {
  font-size: 14px;
  font-weight: 750;
  color: var(--text);
}

.apple-password-desc {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--muted);
}

.password-result-card {
  padding: 14px;
  border-radius: 14px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.password-result-label {
  font-size: 11px;
  color: var(--muted-2);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.password-result-row {
  margin-top: 8px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
}

.password-result-value {
  min-height: 34px;
  padding: 8px 10px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.08);
  color: var(--text);
  font-size: 14px;
  line-height: 1.4;
  word-break: break-all;
}

.password-generator-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
}

.password-generator-footer :deep(.el-button) {
  margin: 0;
}

.mono {
  font-family: var(--mono);
}

@media (max-width: 640px) {
  .password-generator-footer :deep(.el-button) {
    flex: 1 1 calc(50% - 10px);
  }
  .password-result-row,
  .password-option-grid {
    grid-template-columns: 1fr;
  }

  .password-length-row {
    align-items: stretch;
    flex-direction: column;
    gap: 10px;
  }

  .password-length-slider {
    min-width: 0;
    width: 100%;
  }

  .password-length-row :deep(.el-input-number) {
    flex: none;
    width: 100%;
  }

  .password-generator-mode-tabs {
    grid-template-columns: 1fr;
  }
}
</style>

<style>
.password-generator-overlay .el-dialog {
  margin-top: 8vh !important;
}

@media (max-width: 768px) {
  .password-generator-overlay .el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
    display: flex !important;
    flex-direction: column !important;
    overflow: hidden !important;
  }

  .password-generator-overlay .el-dialog__header {
    flex: 0 0 auto !important;
    padding: 14px 16px 10px !important;
  }

  .password-generator-overlay .el-dialog__body {
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow: auto !important;
    padding: 10px 12px 12px !important;
  }
}
</style>