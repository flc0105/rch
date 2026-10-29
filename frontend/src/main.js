import {createApp} from 'vue'
import { registerElementPlusComponents } from './utils/elementPlusRegistry.js'
// Element Plus components and v-loading are registered from explicit named imports.
// Keep service styles for explicit JavaScript API calls (messages, confirms, notices).
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import 'element-plus/es/components/notification/style/css'
import 'element-plus/es/components/loading/style/css'
import './styles/mobileDialogs.css'
import { installMobileDialogScrollLock } from './utils/mobileDialogScrollLock.js'
// The standalone Screen View tab shares this authenticated entry without mounting the main dashboard.

async function mountApp() {
    const standalone = new URLSearchParams(window.location.search).has('screen_view_client')
    const { default: Root } = standalone
        ? await import('./ScreenViewTab.vue')
        : await import('./App.vue')

    const app = createApp(Root)
    registerElementPlusComponents(app)
    const stopMobileDialogScrollLock = installMobileDialogScrollLock()
    app.mount('#app')
    app.onUnmount(stopMobileDialogScrollLock)
}

mountApp()