<template>
  <canvas ref="canvas" class="screen-view-image screen-view-delta-canvas" />
</template>

<script>
export default {
  name: 'KeyframeDeltaScreenRenderer',

  data() {
    return {
      baseCanvas: null,
      baseSeq: 0,
      renderedSeq: 0,
      pendingKeyframe: null,
      pendingDelta: null,
      decodingBaseSeq: 0,
      renderTask: null,
      renderGeneration: 0,
    }
  },

  mounted() {
    this.baseCanvas = document.createElement('canvas')
  },

  methods: {
    reset() {
      this.renderGeneration += 1
      this.baseSeq = 0
      this.renderedSeq = 0
      this.pendingKeyframe = null
      this.pendingDelta = null
      this.decodingBaseSeq = 0
      this.renderTask = null

      const canvas = this.$refs.canvas
      if (canvas) {
        canvas.width = 0
        canvas.height = 0
      }
      if (this.baseCanvas) {
        this.baseCanvas.width = 0
        this.baseCanvas.height = 0
      }
    },

    applyFrame(frame = {}) {
      const frameType = String(frame.frame_type || '').trim().toLowerCase()
      const seq = Number(frame.seq || 0)
      if (!seq || !frame.frame) return Promise.resolve(false)

      if (frameType === 'keyframe') {
        if (seq <= Math.max(this.baseSeq, this.decodingBaseSeq) ||
            (this.pendingKeyframe && seq <= Number(this.pendingKeyframe.seq))) {
          return Promise.resolve(false)
        }
        this.pendingKeyframe = frame
        this.pendingDelta = null
      } else if (frameType === 'delta') {
        const expectedBase = Number(this.pendingKeyframe?.seq || this.decodingBaseSeq || this.baseSeq)
        if (!expectedBase || Number(frame.base_seq || 0) !== expectedBase || seq <= this.renderedSeq) {
          return Promise.resolve(false)
        }
        if (this.pendingDelta && seq <= Number(this.pendingDelta.seq || 0)) return Promise.resolve(false)
        // Every Delta is independently relative to its Keyframe. Keep only
        // the freshest patch instead of decoding old frames in a FIFO queue.
        this.pendingDelta = frame
      } else {
        return Promise.resolve(false)
      }

      if (!this.renderTask) this.startRenderTask()
      return this.renderTask
    },

    startRenderTask() {
      const generation = this.renderGeneration
      const task = this.drainFrames(generation)
      this.renderTask = task
      void task.finally(() => {
        if (this.renderTask !== task) return
        this.renderTask = null
        // A frame may arrive between drain completion and its cleanup.
        if (generation === this.renderGeneration && (this.pendingKeyframe || this.pendingDelta)) {
          this.startRenderTask()
        }
      })
    },

    async drainFrames(generation) {
      let renderedAny = false
      while (generation === this.renderGeneration && (this.pendingKeyframe || this.pendingDelta)) {
        const frame = this.pendingKeyframe || this.pendingDelta
        const isKeyframe = frame.frame_type === 'keyframe'
        if (isKeyframe) {
          this.pendingKeyframe = null
          this.decodingBaseSeq = Number(frame.seq)
        } else {
          this.pendingDelta = null
        }

        try {
          const rendered = isKeyframe
            ? await this.renderKeyframe(frame, generation)
            : await this.renderDelta(frame, generation)
          renderedAny = rendered || renderedAny
        } catch (_) {
          // A failed JPEG should not prevent the next valid frame from rendering.
        }
        if (generation !== this.renderGeneration) break
        if (isKeyframe) this.decodingBaseSeq = 0
      }
      return renderedAny
    },

    async renderKeyframe(frame, generation) {
      const width = Number(frame.width || 0)
      const height = Number(frame.height || 0)
      const seq = Number(frame.seq || 0)
      if (!width || !height || !seq || !frame.frame) return false

      const image = await this.decodeJpeg(frame.frame)
      if (generation !== this.renderGeneration ||
          (this.pendingKeyframe && Number(this.pendingKeyframe.seq) > seq)) return false

      const canvas = this.$refs.canvas
      if (!canvas || !this.baseCanvas) return false
      canvas.width = width
      canvas.height = height
      this.baseCanvas.width = width
      this.baseCanvas.height = height

      const baseContext = this.baseCanvas.getContext('2d')
      const context = canvas.getContext('2d')
      if (!baseContext || !context) return false

      baseContext.clearRect(0, 0, width, height)
      baseContext.drawImage(image, 0, 0, width, height)
      context.clearRect(0, 0, width, height)
      context.drawImage(this.baseCanvas, 0, 0)
      this.baseSeq = seq
      this.renderedSeq = seq
      return true
    },

    async renderDelta(frame, generation) {
      const canvas = this.$refs.canvas
      if (!canvas || !this.baseCanvas || !this.baseSeq) return false

      const baseSeq = Number(frame.base_seq || 0)
      const width = Number(frame.width || 0)
      const height = Number(frame.height || 0)
      if (baseSeq !== this.baseSeq || width !== canvas.width || height !== canvas.height) return false
      if (!frame.frame) return false

      const image = await this.decodeJpeg(frame.frame)
      if (generation !== this.renderGeneration || baseSeq !== this.baseSeq ||
          this.pendingKeyframe ||
          (this.pendingDelta && Number(this.pendingDelta.seq) > Number(frame.seq))) return false

      const patchX = Number(frame.patch_x || 0)
      const patchY = Number(frame.patch_y || 0)
      const patchWidth = Number(frame.patch_width || 0)
      const patchHeight = Number(frame.patch_height || 0)
      if (!patchWidth || !patchHeight) return false

      const context = canvas.getContext('2d')
      if (!context) return false

      // Every Delta is relative to the fixed Keyframe, not the previous Delta.
      context.clearRect(0, 0, width, height)
      context.drawImage(this.baseCanvas, 0, 0)
      context.drawImage(image, patchX, patchY, patchWidth, patchHeight)
      this.renderedSeq = Number(frame.seq)
      return true
    },

    decodeJpeg(base64Data) {
      return new Promise((resolve, reject) => {
        const image = new Image()
        image.onload = () => resolve(image)
        image.onerror = () => reject(new Error('Failed to decode screen frame'))
        image.src = `data:image/jpeg;base64,${base64Data}`
      })
    },
  },
}
</script>
