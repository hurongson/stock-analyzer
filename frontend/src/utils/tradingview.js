// TradingView Widget 动态挂载工具（A股）
// 说明：TradingView 部件通过外部脚本 + 同容器 <script> 内 JSON 配置初始化，
// Vue 模板里直接写 <script> 不会执行，因此统一在 onMounted 后用本模块动态注入。

const ADV_SRC = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'
const HEAT_SRC = 'https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js'

// A股6位代码 -> TradingView symbol
export function tvSymbol(code) {
  const c = String(code).replace(/\D/g, '').padStart(6, '0')
  if (c.startsWith('6')) return 'SSE:' + c          // 上交所（主板/科创板）
  if (c.startsWith('4') || c.startsWith('8') || c.startsWith('920')) return 'BJSE:' + c // 北交所
  return 'SZSE:' + c                                 // 深交所（主板 000/002、创业板 300）
}

// 通用嵌入：el 为容器元素（需有明确宽高），src 为部件脚本，config 为配置对象
function embed(el, src, config) {
  if (!el) return
  el.innerHTML = ''
  el.style.position = 'relative'

  const outer = document.createElement('div')
  outer.className = 'tradingview-widget-container'
  outer.style.width = '100%'
  outer.style.height = '100%'

  const inner = document.createElement('div')
  inner.className = 'tradingview-widget-container__widget'
  inner.style.width = '100%'
  inner.style.height = '100%'
  outer.appendChild(inner)

  // TradingView 加载后会读取该 script 标签内的 JSON 文本作为配置
  const s = document.createElement('script')
  s.type = 'text/javascript'
  s.async = true
  s.src = src
  s.text = JSON.stringify(config)
  outer.appendChild(s)

  el.appendChild(outer)

  // 降级提示：若 6 秒后仍未出现 iframe，说明当前网络可能无法访问 TradingView
  const note = document.createElement('div')
  note.textContent = '图表由 TradingView 提供；若长时间空白，可能是当前网络无法访问 TradingView，可切换网络后刷新。'
  note.style.cssText = 'position:absolute;left:0;right:0;bottom:6px;text-align:center;font-size:11px;color:#9aa7b1;pointer-events:none;'
  el.appendChild(note)
  setTimeout(() => { if (outer.querySelector('iframe')) note.remove() }, 6000)
}

// 高级走势图（专业 K 线 + 技术指标）
export function mountAdvancedChart(el, code) {
  embed(el, ADV_SRC, {
    autosize: true,
    symbol: tvSymbol(code),
    interval: 'D',
    timezone: 'Asia/Shanghai',
    theme: 'light',
    style: '1',
    locale: 'zh_CN',
    backgroundColor: '#ffffff',
    gridColor: 'rgba(0,0,0,0.06)',
    hide_side_toolbar: false,
    allow_symbol_change: true,
    save_image: false,
    support_host: 'https://www.tradingview.com'
  })
}

// 股票热力图；dataSource 取 'SSE'（上交所）或 'SZSE'（深交所）
export function mountHeatmap(el, dataSource = 'SSE') {
  embed(el, HEAT_SRC, {
    autosize: true,
    dataSource,
    grouping: 'sector',
    blockSize: 'market_cap_basic',
    blockColor: 'change',
    locale: 'zh_CN',
    colorTheme: 'light',
    hasLocaleDate: true,
    support_host: 'https://www.tradingview.com'
  })
}
