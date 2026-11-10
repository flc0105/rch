// Terminal output history limits. All sizes are UTF-8 bytes; none limits the saved history.
// Tune these together and verify long JSON lines and mobile scrolling after changing them.
export const TERMINAL_HISTORY = Object.freeze({
  initialLines: 300,
  initialBytes: 128 * 1024,
  loadLines: 200,
  loadBytes: 64 * 1024,
  visibleLines: 600,
  visibleBytes: 256 * 1024,
  displaySegmentChars: 4096, // Split huge logical lines for DOM only; exports rejoin fragments.
  cacheLines: 2000,
  cacheBytes: 2 * 1024 * 1024,
  chunkBytes: 64 * 1024,
  flushDelayMs: 120,
  scrollEdgePx: 160,
  bottomTolerancePx: 60,
})
