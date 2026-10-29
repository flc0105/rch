import {createApp} from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './styles/mobileDialogs.css'
import { installMobileDialogScrollLock } from './utils/mobileDialogScrollLock.js'
// The standalone Screen View tab shares this authenticated entry without mounting the main dashboard.

async function mountApp() {
    const standalone = new URLSearchParams(window.location.search).has('screen_view_client')
    const { default: Root } = standalone
        ? await import('./ScreenViewTab.vue')
        : await import('./App.vue')

    const app = createApp(Root).use(ElementPlus)
    const stopMobileDialogScrollLock = installMobileDialogScrollLock()
    app.mount('#app')
    app.onUnmount(stopMobileDialogScrollLock)
}

mountApp()