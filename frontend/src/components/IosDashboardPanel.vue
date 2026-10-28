<template>
  <div class="ios-dashboard">
    <header class="ios-dashboard-header">
      <div>
        <div class="ios-dashboard-title">iOS Dashboard</div>
        <div class="ios-dashboard-caption">{{ hostname || 'iOS Device' }}</div>
      </div>
      <div class="ios-dashboard-live">
        <div class="ios-dashboard-live-badge" :class="`ios-dashboard-live-${displayState}`">
          <span class="ios-dashboard-live-dot"></span>
          {{ displayLabel }}
        </div>
        <small>{{ updatedText }}</small>
      </div>
    </header>

    <div v-if="error" class="ios-dashboard-error">{{ error }}</div>

    <div class="ios-dashboard-grid">
      <section class="ios-metric ios-metric-highlight">
        <div class="ios-metric-label">Battery</div>
        <div class="ios-metric-value">{{ percent(battery.percent) }}</div>
        <el-progress :percentage="bounded(battery.percent)" :stroke-width="7" :show-text="false" />
        <div class="ios-metric-detail">{{ battery.state || 'Unknown' }} · Low Power {{ data.low_power == null ? '—' : data.low_power ? 'On' : 'Off' }}</div>
      </section>
      <section class="ios-metric">
        <div class="ios-metric-label">System Memory</div>
        <div class="ios-metric-value">{{ percent(memory.percent) }}</div>
        <el-progress v-if="memory.percent != null" :percentage="bounded(memory.percent)" :stroke-width="7" :show-text="false" />
        <div class="ios-metric-detail">{{ bytes(memory.used) }} used / {{ bytes(memory.total) }} total</div>
        <div class="ios-metric-detail">{{ bytes(memory.available) }} available</div>
      </section>
      <section class="ios-metric">
        <div class="ios-metric-label">Storage</div>
        <div class="ios-metric-value ios-metric-value-small">{{ storageBytes(disk.free) }}</div>
        <div class="ios-metric-detail">Free of {{ storageBytes(disk.total) }}</div>
        <el-progress v-if="disk.total > 0 && disk.free != null" :percentage="bounded((1 - disk.free / disk.total) * 100)" :stroke-width="6" :show-text="false" />
      </section>
      <section class="ios-metric">
        <div class="ios-metric-label">Uptime</div>
        <div class="ios-metric-value ios-metric-value-small">{{ uptime(data.uptime_seconds) }}</div>
        <div class="ios-metric-detail">Since device boot</div>
      </section>
    </div>

    <div class="ios-dashboard-sections">
      <section class="ios-dashboard-section">
        <h3>Hardware</h3>
        <div class="ios-dashboard-detail-grid">
          <div class="ios-detail"><span>CPU</span><strong>{{ cpu.active ?? '—' }} active / {{ cpu.total ?? '—' }} total</strong></div>
          <div class="ios-detail"><span>Thermal</span><strong>{{ data.thermal || '—' }}</strong></div>
          <div class="ios-detail"><span>App memory</span><strong>{{ bytes(memory.app_resident) }}</strong></div>
        </div>
      </section>
      <section class="ios-dashboard-section">
        <h3>Display</h3>
        <div class="ios-detail"><span>Resolution</span><strong>{{ dimensions(screen.pixels, 'px') }}</strong></div>
        <div class="ios-detail"><span>Display points</span><strong>{{ dimensions(screen.points, 'pt') }}</strong></div>
        <div class="ios-detail"><span>Scale</span><strong>{{ screen.scale == null ? '—' : screen.scale + '×' }}</strong></div>
        <div class="ios-detail"><span>Brightness</span><strong>{{ percent(screen.brightness) }}</strong></div>
      </section>
      <section class="ios-dashboard-section">
        <h3>Network</h3>
        <div class="ios-detail"><span>Route IP</span><strong>{{ network.route_ip || 'Unavailable' }}</strong></div>
        <div v-for="item in (network.interfaces || [])" :key="item.name + item.ip" class="ios-detail">
          <span>{{ item.name }}</span><strong>{{ item.ip }}</strong>
        </div>
        <div v-if="!network.interfaces?.length" class="ios-dashboard-muted">No visible interfaces</div>
      </section>
      <section class="ios-dashboard-section">
        <h3>Audio Output</h3>
        <div class="ios-detail"><span>Route</span><strong>{{ audio.output || 'Unavailable' }}</strong></div>
        <div class="ios-detail"><span>Sample rate</span><strong>{{ audio.sample_rate == null ? '—' : Math.round(audio.sample_rate).toLocaleString() + ' Hz' }}</strong></div>
        <div class="ios-detail"><span>Output latency</span><strong>{{ audio.output_latency_ms == null ? '—' : audio.output_latency_ms + ' ms' }}</strong></div>
        <div class="ios-detail"><span>Volume</span><strong>{{ percent(audio.volume_percent) }}</strong></div>
      </section>
      <section class="ios-dashboard-section">
        <h3>Library</h3>
        <div class="ios-dashboard-detail-grid ios-library-grid">
          <div class="ios-detail"><span>Photos</span><strong>{{ count(library.photos) }}</strong></div>
          <div class="ios-detail"><span>Music</span><strong>{{ count(library.music) }}</strong></div>
          <div class="ios-detail"><span>Contacts</span><strong>{{ count(library.contacts) }}</strong></div>
        </div>
      </section>
    </div>
  </div>
</template>

<script>
export default {
  name: 'IosDashboardPanel',
  props: {
    data: { type: Object, default: () => ({}) },
    hostname: { type: String, default: '' },
    status: { type: String, default: 'idle' },
    error: { type: String, default: '' },
    updatedText: { type: String, default: '' },
    intervalMs: { type: Number, default: 5000 },
  },
  computed: {
    displayState() {
      if (this.error || this.status === 'error') return 'error'
      if (this.status === 'live' || this.status === 'open') return 'live'
      if (this.status === 'opening') return 'opening'
      return 'idle'
    },
    displayLabel() {
      if (this.displayState === 'live') {
        const ms = Number(this.intervalMs)
        const cadence = Number.isFinite(ms) && ms > 0
          ? (ms >= 1000 ? `${Number((ms / 1000).toFixed(2))} s` : `${Math.round(ms)} ms`)
          : ''
        return cadence ? `LIVE · ${cadence}` : 'LIVE'
      }
      return ({ opening: 'CONNECTING', error: 'ERROR', idle: 'IDLE' })[this.displayState]
    },
    battery() { return this.data.battery || {} },
    disk() { return this.data.disk || {} },
    cpu() { return this.data.cpu || {} },
    memory() { return this.data.memory || {} },
    library() { return this.data.library || {} },
    screen() { return this.data.screen || {} },
    network() { return this.data.network || {} },
    audio() { return this.data.audio || {} },
  },
  methods: {
    bounded(v) { return Number.isFinite(Number(v)) && v != null ? Math.max(0, Math.min(100, Number(v))) : 0 },
    percent(v) { return v == null || !Number.isFinite(Number(v)) ? '—' : `${Math.round(Number(v))}%` },
    count(v) { return v == null || !Number.isSafeInteger(Number(v)) || Number(v) < 0 ? '—' : Number(v).toLocaleString() },
    bytes(v) {
      if (v == null || !Number.isFinite(Number(v))) return '—'
      const n = Number(v)
      return n >= 1024 ** 3 ? `${(n / (1024 ** 3)).toFixed(1)} GB` : `${(n / (1024 ** 2)).toFixed(1)} MB`
    },
    storageBytes(v) {
      if (v == null || !Number.isFinite(Number(v))) return '—'
      const n = Number(v)
      return n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${(n / 1e6).toFixed(1)} MB`
    },
    dimensions(v, unit) { return Array.isArray(v) && v.length === 2 ? `${v[0]} × ${v[1]} ${unit}` : '—' },
    uptime(v) {
      if (v == null || !Number.isFinite(Number(v))) return '—'
      const sec = Math.max(0, Math.floor(Number(v)))
      const days = Math.floor(sec / 86400)
      const hours = Math.floor((sec % 86400) / 3600)
      const minutes = Math.floor((sec % 3600) / 60)
      return days ? `${days}d ${hours}h ${minutes}m` : `${hours}h ${minutes}m`
    },
  },
}
</script>

<style scoped>
.ios-dashboard { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.ios-dashboard-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; padding: 2px; }
.ios-dashboard-title { font-weight: 700; font-size: 16px; color: var(--text); }
.ios-dashboard-caption { margin-top: 3px; font-size: 12px; color: var(--muted); }
.ios-dashboard-live { display: flex; flex-direction: column; align-items: flex-end; gap: 5px; color: var(--muted); font-size: 12px; }
.ios-dashboard-live-badge { display: inline-flex; align-items: center; gap: 7px; padding: 5px 9px; border-radius: 20px; background: rgba(148,163,184,.12); font-weight: 650; font-size: 11px; letter-spacing: .035em; }
.ios-dashboard-live-live { color: #16a34a; background: rgba(22,163,74,.09); }
.ios-dashboard-live-error { color: #dc2626; background: rgba(220,38,38,.07); }
.ios-dashboard-live-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.ios-dashboard-live small { font-size: 11px; text-align: right; }
.ios-dashboard-error { font-size: 12px; padding: 9px; border: 1px solid #fecaca; border-radius: 8px; color: #b91c1c; }
.ios-dashboard-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.ios-metric, .ios-dashboard-section { min-width: 0; border: 1px solid rgba(15,23,42,.07); background: #f8fafc; border-radius: 12px; padding: 14px; }
.ios-metric-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .035em; }
.ios-metric-value { font-size: 27px; font-weight: 700; margin: 8px 0; color: var(--text); }
.ios-metric-value-small { font-size: 21px; }
.ios-metric-detail { margin-top: 8px; font-size: 11px; line-height: 17px; color: var(--muted); }
.ios-metric :deep(.el-progress) { margin-top: 10px; }
.ios-dashboard-sections { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 10px; }
.ios-dashboard-section:last-child { grid-column: 1 / -1; }
.ios-dashboard-section h3 { margin: 0 0 10px; font-size: 13px; color: var(--text); }
.ios-dashboard-detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); column-gap: 16px; }
.ios-library-grid { grid-template-columns: repeat(3, minmax(0,1fr)); }
.ios-detail { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; min-width: 0; padding: 7px 0; border-bottom: 1px solid rgba(15,23,42,.05); font-size: 12px; }
.ios-detail span { color: var(--muted); flex: 0 0 auto; }
.ios-detail strong { color: var(--text); font-weight: 600; text-align: right; overflow-wrap: anywhere; min-width: 0; }
.ios-dashboard-muted { color: var(--muted); font-size: 12px; padding: 8px 0; }
@media (max-width: 850px) { .ios-dashboard-grid { grid-template-columns: repeat(2, minmax(0,1fr)); } .ios-dashboard-detail-grid { grid-template-columns: 1fr; } }
@media (max-width: 570px) { .ios-dashboard-header { flex-direction: column; } .ios-dashboard-live { align-items: flex-start; } .ios-dashboard-live small { text-align: left; } .ios-dashboard-sections { grid-template-columns: 1fr; } .ios-dashboard-section:last-child { grid-column: auto; } .ios-metric { padding: 11px; } }
</style>
