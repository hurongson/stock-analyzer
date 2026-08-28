import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './assets/main.css'
import { registerSW } from 'virtual:pwa-register'

// 注册 PWA Service Worker
const updateSW = registerSW({
  onNeedRefresh() {
    console.log('[PWA] 发现新版本，刷新页面更新')
    if (confirm('发现新版本，是否立即刷新？')) {
      updateSW(true)
    }
  },
  onOfflineReady() {
    console.log('[PWA] 应用已准备好离线使用')
  },
  onRegistered(r) {
    console.log('[PWA] Service Worker 已注册')
    // 每小时检查一次更新
    setInterval(() => {
      r.update()
    }, 60 * 60 * 1000)
  },
  onRegisterError(error) {
    console.error('[PWA] Service Worker 注册失败:', error)
  }
})

const app = createApp(App)
app.use(router)
app.mount('#app')
