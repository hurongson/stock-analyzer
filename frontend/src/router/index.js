import { createRouter, createWebHashHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import StockDetail from '../views/StockDetail.vue'
import Screener from '../views/Screener.vue'
import History from '../views/History.vue'

const routes = [
  { path: '/', name: 'Dashboard', component: Dashboard, meta: { title: '分析看板' } },
  { path: '/stock/:code', name: 'StockDetail', component: StockDetail, meta: { title: '个股详情' } },
  { path: '/screener', name: 'Screener', component: Screener, meta: { title: '选股结果' } },
  { path: '/history', name: 'History', component: History, meta: { title: '历史报告' } },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

router.afterEach((to) => {
  document.title = `${to.meta.title || '股票分析'} - 股票分析系统`
})

export default router
