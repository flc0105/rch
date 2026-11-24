<template>
  <img
    :src="currentSrc"
    alt="Remote screen preview"
    class="screen-view-image"
    draggable="false"
    @load="finishFrame(true)"
    @error="finishFrame(false)"
  >
</template>

<script>
export default {
  name: 'FullJpegScreenRenderer',
  emits: ['rendered'],
  props: {
    src: {
      type: String,
      default: '',
    },
    seq: {
      type: Number,
      default: 0,
    },
  },
  data() {
    return {
      currentSrc: '',
      currentSeq: 0,
      started: 0,
      loadingFrame: false,
      loaded: false,
      pending: null,
    }
  },
  watch: {
    seq: {
      immediate: true,
      handler() {
        if (!this.src || !this.seq) return
        this.pending = { src: this.src, seq: this.seq }
        this.startPending()
      },
    },
  },
  methods: {
    startPending() {
      if (this.loadingFrame || !this.pending) return
      const packet = this.pending
      this.pending = null
      this.currentSeq = packet.seq
      this.started = performance.now()
      if (packet.src === this.currentSrc && this.loaded) {
        this.$emit('rendered', { seq: packet.seq, duration: 0 })
        return
      }
      // An identical failed JPEG cannot produce a new load event. Wait for a valid source.
      if (packet.src === this.currentSrc) return
      this.loadingFrame = true
      this.loaded = false
      this.currentSrc = packet.src
    },
    finishFrame(success) {
      if (!this.loadingFrame) return
      this.loadingFrame = false
      this.loaded = success
      if (success) this.$emit('rendered', { seq: this.currentSeq, duration: performance.now() - this.started })
      this.startPending()
    },
  },
}
</script>
