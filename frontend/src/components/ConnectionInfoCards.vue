<template>
  <section class="info-grid">
    <div class="info-card">
      <div class="info-label">Hostname</div>
      <div class="info-value">{{ connection.hostname || '-' }}</div>
    </div>

    <div class="info-card">
      <div class="info-label">IP Address</div>
      <div class="info-value">{{ formatAddress(connection.addr) || '-' }}</div>
    </div>

    <div class="info-card">
      <div class="info-label">Platform</div>
      <div class="info-value">
        {{ formatOsLabel(connection.os_type, connection.os_ver) }}
      </div>
    </div>

    <div class="info-card">
      <div class="info-label">Status</div>
      <div class="info-value">{{ getConnectionStatusText(connection) }}</div>
    </div>

    <div class="info-card">
      <div class="info-label">RTT</div>
      <div class="info-value">{{ formatConnectionRtt(connection) }}</div>
    </div>

    <div class="info-card">
      <div class="info-label">Integrity</div>
      <div class="info-value">{{ connection.integrity || '-' }}</div>
    </div>

    <div class="info-card info-card-wide-2">
      <div class="info-label">Client ID</div>
      <div class="info-value">{{ connection.client_id || '-' }}</div>
    </div>

    <div class="info-card info-card-wide-2">
      <div class="info-label">Working Directory</div>
      <div class="info-value mono">{{ connection.cwd || '-' }}</div>
    </div>
  </section>
</template>

<script>
import { formatConnectionRtt as formatConnectionRttValue, formatConnectionStatus as formatConnectionStatusValue, getConnectionDisplayState as getConnectionDisplayStateValue } from '../utils/connectionInfoFormatting.js'

export default {
  name: 'ConnectionInfoCards',

  props: {
    connection: {
      type: Object,
      required: true,
    },

    statusNowTick: {
      type: Number,
      default: () => Date.now(),
    },
  },

  methods: {
    // Keep the connection card and Terminal Context on the same status rules.
    getConnectionDisplayState(conn) {
      return getConnectionDisplayStateValue(conn, this.statusNowTick)
    },

    getConnectionStatusText(conn) {
      return formatConnectionStatusValue(conn, this.statusNowTick)
    },

    formatConnectionRtt(conn) {
      return formatConnectionRttValue(conn)
    },

    formatOsLabel(osType, osVer) {
      const type = osType || 'Unknown'
      return osVer ? `${type}` : type
    },

    formatAddress(addr) {
      if (!addr) return '-'
      const raw = String(addr)
      const parts = raw.split(':')
      if (parts.length >= 2) return parts.slice(0, -1).join(':') || raw
      return raw
    },
  },
}
</script>

<style scoped>
/* ========== 连接信息卡片 ========== */
.info-grid {
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--line);
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  flex-shrink: 0;
}

.info-card {
  padding: 14px 16px;
  border-radius: var(--radius-md);
  background: var(--bg-card);
  border: 1px solid rgba(15, 23, 42, 0.05);
  min-width: 0;
}

.info-card-wide-2 {
  grid-column: span 2;
}

.info-label {
  font-size: 11px;
  color: var(--muted-2);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.info-value {
  margin-top: 7px;
  font-size: 14px;
  font-weight: 650;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.info-value.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

@media (max-width: 1200px) {
  .info-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 960px) {
  .info-grid {
    min-width: 0;
    max-width: 100%;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>