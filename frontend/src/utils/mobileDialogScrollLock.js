const BODY_LOCK_CLASS = 'rch-mobile-dialog-open'
const BODY_STYLE_PROPERTIES = ['position', 'top', 'left', 'right', 'width', 'height', 'overflow']
const APP_STYLE_PROPERTIES = ['overflow-y']

function snapshotStyle(element, properties) {
  if (!element?.style) return null

  return Object.fromEntries(properties.map(property => [property, {
    value: element.style.getPropertyValue(property),
    priority: element.style.getPropertyPriority(property),
  }]))
}

function restoreStyle(element, snapshot) {
  if (!element?.style || !snapshot) return

  for (const [property, saved] of Object.entries(snapshot)) {
    if (saved.value) {
      element.style.setProperty(property, saved.value, saved.priority)
    } else {
      element.style.removeProperty(property)
    }
  }
}

function hasVisibleDialog(documentRef, windowRef) {
  return Array.from(documentRef.querySelectorAll('.el-overlay')).some(overlay => {
    const dialog = overlay.querySelector('.el-dialog, .el-message-box')
    if (!dialog || overlay.getAttribute('aria-hidden') === 'true') return false
    if (overlay.style?.display === 'none' || dialog.style?.display === 'none') return false

    if (typeof windowRef.getComputedStyle === 'function') {
      try {
        const overlayStyle = windowRef.getComputedStyle(overlay)
        const dialogStyle = windowRef.getComputedStyle(dialog)
        if (overlayStyle.display === 'none' || overlayStyle.visibility === 'hidden') return false
        if (dialogStyle.display === 'none' || dialogStyle.visibility === 'hidden') return false
      } catch {
        // The inline display and aria-hidden checks still cover test DOMs without full style support.
      }
    }

    return true
  })
}

/** Lock page scrolling while an Element Plus dialog is open on a phone. */
export function installMobileDialogScrollLock({
  documentRef = typeof document !== 'undefined' ? document : null,
  windowRef = typeof window !== 'undefined' ? window : null,
  MutationObserverClass = typeof MutationObserver !== 'undefined' ? MutationObserver : null,
  breakpoint = 768,
} = {}) {
  if (!documentRef?.body || !windowRef) return () => {}

  const body = documentRef.body
  const app = documentRef.getElementById?.('app') || null
  const mediaQuery = typeof windowRef.matchMedia === 'function'
    ? windowRef.matchMedia(`(max-width: ${breakpoint}px)`)
    : null

  let locked = false
  let savedBodyStyle = null
  let savedAppStyle = null
  let savedWindowScrollY = 0
  let savedAppScrollTop = 0

  const isMobile = () => mediaQuery ? mediaQuery.matches : Number(windowRef.innerWidth || 0) <= breakpoint

  const lock = () => {
    if (locked) return
    locked = true

    savedWindowScrollY = Math.max(0, Number(windowRef.scrollY ?? windowRef.pageYOffset ?? 0))
    savedAppScrollTop = Math.max(0, Number(app?.scrollTop || 0))
    savedBodyStyle = snapshotStyle(body, BODY_STYLE_PROPERTIES)
    savedAppStyle = snapshotStyle(app, APP_STYLE_PROPERTIES)

    body.classList.add(BODY_LOCK_CLASS)
    body.style.setProperty('position', 'fixed')
    body.style.setProperty('top', `${-savedWindowScrollY}px`)
    body.style.setProperty('left', '0')
    body.style.setProperty('right', '0')
    body.style.setProperty('width', '100%')
    body.style.setProperty('height', '100%')
    body.style.setProperty('overflow', 'hidden')

    // On mobile the app root is the page's scroll container; preserve its current offset.
    app?.style?.setProperty('overflow-y', 'hidden')
  }

  const unlock = () => {
    if (!locked) return
    locked = false

    body.classList.remove(BODY_LOCK_CLASS)
    restoreStyle(body, savedBodyStyle)
    restoreStyle(app, savedAppStyle)

    if (app) app.scrollTop = savedAppScrollTop
    try {
      windowRef.scrollTo?.(0, savedWindowScrollY)
    } catch {
      // Some embedded browsers do not expose programmatic window scrolling.
    }

    savedBodyStyle = null
    savedAppStyle = null
  }

  const refresh = () => {
    if (isMobile() && hasVisibleDialog(documentRef, windowRef)) lock()
    else unlock()
  }

  const preventBackgroundTouchMove = event => {
    if (!locked) return
    let target = event.target
    if (target?.nodeType === 3) target = target.parentElement
    if (target?.closest?.('.el-dialog, .el-popper, .el-message-box')) return
    event.preventDefault?.()
  }

  const refreshFromDialogMutations = records => {
    const relevant = records.some(record => {
      if (record.type === 'childList') {
        return record.target === body || Boolean(record.target?.matches?.('.el-overlay'))
      }
      if (record.type === 'attributes') {
        return Boolean(record.target?.matches?.('.el-overlay, .el-dialog, .el-message-box'))
      }
      return false
    })
    if (relevant) refresh()
  }

  const observer = MutationObserverClass ? new MutationObserverClass(refreshFromDialogMutations) : null
  observer?.observe(body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['class', 'style', 'aria-hidden'],
  })

  if (mediaQuery?.addEventListener) mediaQuery.addEventListener('change', refresh)
  else mediaQuery?.addListener?.(refresh)
  windowRef.addEventListener?.('resize', refresh)
  documentRef.addEventListener?.('touchmove', preventBackgroundTouchMove, { capture: true, passive: false })

  refresh()

  return () => {
    observer?.disconnect()
    if (mediaQuery?.removeEventListener) mediaQuery.removeEventListener('change', refresh)
    else mediaQuery?.removeListener?.(refresh)
    windowRef.removeEventListener?.('resize', refresh)
    documentRef.removeEventListener?.('touchmove', preventBackgroundTouchMove, { capture: true })
    unlock()
  }
}
