import { h } from 'vue'
import { ElMessage } from 'element-plus'

// Only the App's transfer drawer needs to know how to open itself.
export const OPEN_TRANSFER_CENTER_KEY = Symbol('rch.openTransferCenter')

export function showTransferStartedToast(message, openTransferCenter) {
  if (typeof openTransferCenter !== 'function') {
    return ElMessage.success(message)
  }

  let toast
  // Element Plus 2.13 renders custom VNodes without its native text wrapper.
  // Apply that wrapper explicitly so typography matches ordinary Message toasts.
  toast = ElMessage.success({
    duration: 5000,
    customClass: 'rch-transfer-started-toast',
    message: h('span', { class: 'el-message__content rch-transfer-started-content' }, [
      h('span', { class: 'rch-transfer-started-label' }, String(message)),
      ' ',
      h('a', {
        href: '#',
        class: 'rch-transfer-started-open',
        title: 'Open Transfers',
        'aria-label': 'Open Transfers',
        onClick: event => {
          event?.preventDefault()
          event?.stopPropagation()
          toast?.close()
          try {
            Promise.resolve(openTransferCenter()).catch(() => ElMessage.error('Unable to open Transfers'))
          } catch (_) {
            ElMessage.error('Unable to open Transfers')
          }
        },
      }, 'Transfers'),
    ]),
  })
  return toast
}
