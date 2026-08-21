/**
 * 数据获取工具
 * 从 GitHub Pages 托管的 data 目录读取 JSON 报告
 */

// 数据基础路径（GitHub Pages 上 data 目录与 index.html 同级）
const DATA_BASE = './data'

/**
 * 获取最新报告
 */
export async function fetchLatestReport() {
  try {
    const resp = await fetch(`${DATA_BASE}/latest.json?t=${Date.now()}`)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    return await resp.json()
  } catch (e) {
    console.error('获取最新报告失败:', e)
    return null
  }
}

/**
 * 获取指定日期报告
 */
export async function fetchReportByDate(date) {
  try {
    const resp = await fetch(`${DATA_BASE}/reports/report_${date}.json?t=${Date.now()}`)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    return await resp.json()
  } catch (e) {
    console.error(`获取 ${date} 报告失败:`, e)
    return null
  }
}

/**
 * 获取选股结果
 */
export async function fetchScreenerResult(date = null) {
  const suffix = date ? `_${date}` : ''
  try {
    const resp = await fetch(`${DATA_BASE}/screener${suffix}.json?t=${Date.now()}`)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    return await resp.json()
  } catch (e) {
    console.error('获取选股结果失败:', e)
    return null
  }
}

/**
 * 格式化数字
 */
export function formatNumber(num, decimals = 2) {
  if (num === null || num === undefined || isNaN(num)) return '-'
  return Number(num).toFixed(decimals)
}

/**
 * 格式化金额（万/亿）
 */
export function formatMoney(num) {
  if (!num) return '-'
  if (Math.abs(num) >= 1e8) return (num / 1e8).toFixed(2) + '亿'
  if (Math.abs(num) >= 1e4) return (num / 1e4).toFixed(0) + '万'
  return num.toFixed(0)
}

/**
 * 获取涨跌样式类
 */
export function getChangeClass(val) {
  if (val > 0) return 'up'
  if (val < 0) return 'down'
  return 'flat'
}

/**
 * 获取评分样式类
 */
export function getScoreClass(score) {
  if (score >= 60) return 'score-high'
  if (score >= 45) return 'score-mid'
  return 'score-low'
}

/**
 * 获取评级样式类
 */
export function getRatingClass(rating) {
  if (!rating) return 'rating-neutral'
  if (rating.includes('多') || rating.includes('买入')) return 'rating-bullish'
  if (rating.includes('空') || rating.includes('卖出')) return 'rating-bearish'
  return 'rating-neutral'
}
