<template>
  <div>
    <div v-if="loading" class="loading">
      <div class="loading-spinner"></div>
      <p>加载中...</p>
    </div>

    <div v-else-if="!stockData" class="card">
      <p>未找到该股票的分析数据，请返回 <router-link to="/">首页</router-link> 查看。</p>
    </div>

    <template v-else>
      <!-- 股票基本信息 -->
      <div class="card">
        <div class="stock-header">
          <div>
            <h2 style="font-size: 22px;">{{ stockData.name }}
              <span style="color: #999; font-size: 16px; font-weight: normal;">({{ stockData.code }})</span>
            </h2>
            <div class="stock-price">
              <span class="price">{{ stockData.price }}</span>
              <span :class="getChangeClass(stockData.pct_change)" class="change">
                {{ stockData.pct_change > 0 ? '+' : '' }}{{ formatNumber(stockData.pct_change) }}%
              </span>
            </div>
          </div>
          <div class="stock-rating">
            <div class="total-score" :class="getScoreClass(stockData.total_score)">
              {{ stockData.total_score }}
            </div>
            <div class="score-label">综合评分</div>
            <span :class="['rating-tag', getRatingClass(stockData.rating)]" style="margin-top: 8px;">
              {{ stockData.rating }}
            </span>
            <div style="margin-top: 8px; font-size: 15px; font-weight: 600;">
              操作建议：{{ stockData.action }}
            </div>
          </div>
        </div>
      </div>

      <!-- 五维评分雷达图 -->
      <div class="card">
        <div class="card-title">📊 五维评分</div>
        <div ref="radarChart" style="width: 100%; height: 350px;"></div>
      </div>

      <!-- 三把锁分析 -->
      <div class="card" v-if="stockData.three_locks">
        <div class="card-title">🔒 三把锁分析 <span class="signal-badge" :class="getLockSignalClass(stockData.three_locks.signal)">{{ stockData.three_locks.signal }}</span></div>
        <div class="locks-container">
          <div class="lock-item" :class="{locked: stockData.three_locks.trend_lock?.locked}">
            <div class="lock-icon">{{ stockData.three_locks.trend_lock?.locked ? '🔒' : '🔓' }}</div>
            <div class="lock-name">趋势锁</div>
            <div class="lock-score">{{ stockData.three_locks.trend_lock?.score || 0 }}分</div>
            <div class="lock-status">{{ stockData.three_locks.trend_lock?.locked ? '已点亮' : '未点亮' }}</div>
          </div>
          <div class="lock-item" :class="{locked: stockData.three_locks.activity_lock?.locked}">
            <div class="lock-icon">{{ stockData.three_locks.activity_lock?.locked ? '🔒' : '🔓' }}</div>
            <div class="lock-name">股性锁</div>
            <div class="lock-score">{{ stockData.three_locks.activity_lock?.score || 0 }}分</div>
            <div class="lock-status">{{ stockData.three_locks.activity_lock?.locked ? '已点亮' : '未点亮' }}</div>
          </div>
          <div class="lock-item" :class="{locked: stockData.three_locks.capital_lock?.locked}">
            <div class="lock-icon">{{ stockData.three_locks.capital_lock?.locked ? '🔒' : '🔓' }}</div>
            <div class="lock-name">资金锁</div>
            <div class="lock-score">{{ stockData.three_locks.capital_lock?.score || 0 }}分</div>
            <div class="lock-status">{{ stockData.three_locks.capital_lock?.locked ? '已点亮' : '未点亮' }}</div>
          </div>
        </div>
        <div class="locks-summary">
          <div>点亮数量：<strong>{{ stockData.three_locks.total_locked }}/3</strong></div>
          <div>信号强度：<strong>{{ stockData.three_locks.signal_strength || 0 }}%</strong></div>
        </div>
        <div class="locks-reasons" v-if="stockData.three_locks.trend_lock?.reasons?.length">
          <div class="reason-title">📈 趋势锁依据：</div>
          <ul><li v-for="(r, i) in stockData.three_locks.trend_lock.reasons.slice(0, 3)" :key="i">{{ r }}</li></ul>
        </div>
        <div class="locks-reasons" v-if="stockData.three_locks.activity_lock?.reasons?.length">
          <div class="reason-title">⚡ 股性锁依据：</div>
          <ul><li v-for="(r, i) in stockData.three_locks.activity_lock.reasons.slice(0, 3)" :key="i">{{ r }}</li></ul>
        </div>
        <div class="locks-reasons" v-if="stockData.three_locks.capital_lock?.reasons?.length">
          <div class="reason-title">💰 资金锁依据：</div>
          <ul><li v-for="(r, i) in stockData.three_locks.capital_lock.reasons.slice(0, 3)" :key="i">{{ r }}</li></ul>
        </div>
      </div>

      <!-- 走势分析 -->
      <div class="card" v-if="stockData.trend_analysis">
        <div class="card-title">📊 走势分析 <span class="score-badge" :class="getScoreClass(stockData.trend_analysis.overall_score)">{{ stockData.trend_analysis.overall_score }}分</span></div>
        <div class="trend-overview">
          <div class="trend-item">
            <div class="trend-label">趋势方向</div>
            <div class="trend-value">{{ stockData.trend_analysis.trend?.direction || '-' }}</div>
          </div>
          <div class="trend-item">
            <div class="trend-label">趋势强度</div>
            <div class="trend-value">{{ stockData.trend_analysis.trend?.strength || '-' }}</div>
          </div>
          <div class="trend-item">
            <div class="trend-label">均线排列</div>
            <div class="trend-value">{{ stockData.trend_analysis.ma_analysis?.alignment || '-' }}</div>
          </div>
          <div class="trend-item">
            <div class="trend-label">量价关系</div>
            <div class="trend-value">{{ stockData.trend_analysis.volume_price?.relation || '-' }}</div>
          </div>
        </div>
        <div class="trend-description">{{ stockData.trend_analysis.trend?.description || '' }}</div>
        <div class="key-points" v-if="stockData.trend_analysis.key_points?.length">
          <div class="reason-title">📍 关键点位：</div>
          <ul><li v-for="(p, i) in stockData.trend_analysis.key_points" :key="i">{{ p }}</li></ul>
        </div>
        <div class="patterns" v-if="stockData.trend_analysis.patterns?.length">
          <div class="reason-title">🔍 走势形态：</div>
          <div class="pattern-tags">
            <span v-for="(p, i) in stockData.trend_analysis.patterns" :key="i" 
                  class="pattern-tag" :class="'pattern-' + p.type">
              {{ p.name }} ({{ p.confidence }}%)
            </span>
          </div>
        </div>
        <div class="operation-suggestion">
          <div class="reason-title">💡 操作建议：</div>
          <div>{{ stockData.trend_analysis.operation_suggestion || '' }}</div>
        </div>
      </div>

      <!-- 技术面 -->
      <div class="card">
        <div class="card-title">📈 技术面分析</div>
        <div class="dimension-score">
          技术评分：<span :class="['score-badge', getScoreClass(stockData.technical.technical_score || 50)]">
            {{ stockData.technical.technical_score || 50 }}
          </span>
        </div>
        <ul class="conclusion-list">
          <li v-for="(c, i) in stockData.technical.conclusions || []" :key="i">{{ c }}</li>
        </ul>

        <div v-if="stockData.technical.support_resistance" class="info-grid">
          <div class="info-item">
            <div class="info-label">支撑位1</div>
            <div class="info-value">{{ stockData.technical.support_resistance.support_1 || '-' }}</div>
          </div>
          <div class="info-item">
            <div class="info-label">压力位1</div>
            <div class="info-value">{{ stockData.technical.support_resistance.resistance_1 || '-' }}</div>
          </div>
          <div class="info-item">
            <div class="info-label">MA5</div>
            <div class="info-value">{{ stockData.technical.trend?.ma5 || '-' }}</div>
          </div>
          <div class="info-item">
            <div class="info-label">MA20</div>
            <div class="info-value">{{ stockData.technical.trend?.ma20 || '-' }}</div>
          </div>
        </div>
      </div>

      <!-- 基本面 -->
      <div class="card">
        <div class="card-title">📊 基本面分析</div>
        <div class="dimension-score">
          基本面评分：<span :class="['score-badge', getScoreClass(stockData.fundamental.score || 50)]">
            {{ stockData.fundamental.score || 50 }}
          </span>
        </div>
        <ul class="conclusion-list">
          <li v-for="(c, i) in stockData.fundamental.conclusions || []" :key="i">{{ c }}</li>
        </ul>
      </div>

      <!-- 资金面 -->
      <div class="card">
        <div class="card-title">💹 资金面分析</div>
        <div class="dimension-score">
          资金评分：<span :class="['score-badge', getScoreClass(stockData.capital.score || 50)]">
            {{ stockData.capital.score || 50 }}
          </span>
        </div>
        <ul class="conclusion-list">
          <li v-for="(c, i) in stockData.capital.conclusions || []" :key="i">{{ c }}</li>
        </ul>
      </div>

      <!-- 概念热点 -->
      <div class="card">
        <div class="card-title">🔥 概念热点</div>
        <div class="dimension-score">
          概念评分：<span :class="['score-badge', getScoreClass(stockData.concept.score || 50)]">
            {{ stockData.concept.score || 50 }}
          </span>
        </div>
        <ul class="conclusion-list">
          <li v-for="(c, i) in stockData.concept.conclusions || []" :key="i">{{ c }}</li>
        </ul>
      </div>

      <!-- LLM 深度分析 -->
      <div v-if="stockData.llm_analysis && stockData.llm_analysis.raw" class="card">
        <div class="card-title">🤖 AI 深度分析</div>
        <div class="llm-content" v-html="formatLLM(stockData.llm_analysis.raw)"></div>
      </div>

      <!-- 风险提示 -->
      <div v-if="stockData.risks && stockData.risks.length > 0" class="card risk-card">
        <div class="card-title">⚠️ 风险提示</div>
        <ul class="conclusion-list">
          <li v-for="(r, i) in stockData.risks" :key="i" style="color: #e6a23c;">{{ r }}</li>
        </ul>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import * as echarts from 'echarts'
import { fetchLatestReport, formatNumber, getChangeClass, getScoreClass, getRatingClass } from '../utils/data'

const route = useRoute()
const loading = ref(true)
const stockData = ref(null)
const radarChart = ref(null)

let chartInstance = null

function formatLLM(text) {
  return text.replace(/\n/g, '<br>')
}

function initRadarChart() {
  if (!radarChart.value || !stockData.value) return
  if (chartInstance) chartInstance.dispose()

  chartInstance = echarts.init(radarChart.value)
  const scores = stockData.value.scores || {}
  chartInstance.setOption({
    tooltip: {},
    radar: {
      indicator: [
        { name: '技术面', max: 100 },
        { name: '基本面', max: 100 },
        { name: '资金面', max: 100 },
        { name: '概念热点', max: 100 },
        { name: '综合评分', max: 100 },
      ],
      radius: '65%',
      axisName: { color: '#666', fontSize: 13 },
      splitArea: { areaStyle: { color: ['#fff', '#f8f9fb'] } }
    },
    series: [{
      type: 'radar',
      data: [{
        value: [
          scores.technical || 50,
          scores.fundamental || 50,
          scores.capital || 50,
          scores.concept || 50,
          stockData.value.total_score || 50
        ],
        name: stockData.value.name,
        areaStyle: { color: 'rgba(64, 158, 255, 0.2)' },
        lineStyle: { color: '#409eff', width: 2 },
        itemStyle: { color: '#409eff' }
      }]
    }]
  })
}

async function loadData() {
  loading.value = true
  const code = route.params.code
  const report = await fetchLatestReport()
  if (report && report.stock_analyses) {
    stockData.value = report.stock_analyses.find(a => a.code === code) || null
  }
  loading.value = false
  await nextTick()
  initRadarChart()
}

watch(() => route.params.code, loadData)
onMounted(loadData)
</script>

<style scoped>
.stock-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 20px;
}

.stock-price {
  margin-top: 8px;
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.price {
  font-size: 32px;
  font-weight: 700;
}

.change {
  font-size: 18px;
  font-weight: 600;
}

.stock-rating {
  text-align: center;
}

.total-score {
  width: 70px;
  height: 70px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  font-weight: 700;
  color: #fff;
  margin: 0 auto;
}

.score-label {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}

.dimension-score {
  margin-bottom: 12px;
  font-size: 14px;
}

.conclusion-list {
  list-style: none;
  padding: 0;
}

.conclusion-list li {
  padding: 6px 0;
  border-bottom: 1px dashed #f0f0f0;
  font-size: 13px;
}

.conclusion-list li:last-child {
  border-bottom: none;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.info-item {
  background: #f8f9fb;
  padding: 12px;
  border-radius: 6px;
  text-align: center;
}

.info-label {
  font-size: 12px;
  color: #999;
}

.info-value {
  font-size: 16px;
  font-weight: 600;
  margin-top: 4px;
}

.llm-content {
  background: #f8f9fb;
  padding: 16px;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.8;
  white-space: pre-wrap;
}

.risk-card {
  border-left: 4px solid #e6a23c;
}
</style>
