/**
 * Load optional modules after first paint, one per browser idle opportunity.
 * Hover/click handlers use the same memoized loader independently of this queue.
 */
export function scheduleIdleWarmup(tasks) {
  if (typeof window === 'undefined') return () => {}
  const queue = [...tasks]
  let stopped = false
  let idleHandle = null
  let timerHandle = null
  let frameHandle = null
  let firstFrameHandle = null
  let waitingForLoad = false
  let waitingForVisibility = false

  const schedule = () => {
    if (stopped || !queue.length) return
    if (document.hidden) {
      waitingForVisibility = true
      document.addEventListener('visibilitychange', onVisible)
      return
    }
    const run = () => {
      idleHandle = null
      timerHandle = null
      if (stopped) return
      if (document.hidden) { schedule(); return }
      const task = queue.shift()
      Promise.resolve().then(task).catch(error => {
        console.warn('Optional dialog warmup failed', error)
      }).finally(schedule)
    }
    if (typeof window.requestIdleCallback === 'function') {
      idleHandle = window.requestIdleCallback(run, { timeout: 12000 })
    } else {
      timerHandle = window.setTimeout(run, 600)
    }
  }
  const onVisible = () => {
    if (document.hidden) return
    document.removeEventListener('visibilitychange', onVisible)
    waitingForVisibility = false
    schedule()
  }
  const afterLoad = () => {
    waitingForLoad = false
    if (stopped) return
    firstFrameHandle = window.requestAnimationFrame(() => {
      firstFrameHandle = null
      frameHandle = window.requestAnimationFrame(() => {
        frameHandle = null
        schedule()
      })
    })
  }
  if (document.readyState === 'complete') afterLoad()
  else {
    waitingForLoad = true
    window.addEventListener('load', afterLoad, { once: true })
  }
  return () => {
    stopped = true
    if (waitingForLoad) window.removeEventListener('load', afterLoad)
    if (waitingForVisibility) document.removeEventListener('visibilitychange', onVisible)
    if (firstFrameHandle !== null) window.cancelAnimationFrame(firstFrameHandle)
    if (frameHandle !== null) window.cancelAnimationFrame(frameHandle)
    if (idleHandle !== null) window.cancelIdleCallback?.(idleHandle)
    if (timerHandle !== null) window.clearTimeout(timerHandle)
  }
}
