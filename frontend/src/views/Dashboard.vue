<template>
  <div>
    <!-- 加载状态 -->
    <div v-if="loading" class="loading">
      <div class="loading-spinner"></div>
      <p>正在加载分析数据...</p>
    </div>

    <!-- 无数据 -->
    <div v-else-if="!report" class="card">
      <h3>暂无分析数据</h3>
      <p style="color: #999; margin-top: 8px;">
        请先配置 GitHub Actions 并运行一次分析任务，数据将自动生成。
      </p>
    </div>

    <template v-else>
      <!-- 顶部概览 -->
      <div class="card">
        <div class="card-title">
          📊 分析概览
          <span style="margin-left: auto; font-size: 13px; color: #999; font-weight: normal;">
            {{ report.date }}
          </span>
        </div>
        <div class="overview-grid">
          <div class="overview-item">
            <div class="overview-label">自选股数</div>
            <div class="overview-value">{{ validAnalyses.length }}</div>
          </div>
          <div class="overview-item">
            <div class="overview-label">看多</div>
            <div class="overview-value up">{{ bullishCount }}</div>
          </div>
          <div class="overview-item">
            <div class="overview-label">中性</div>
            <div class="overview-value flat">{{ neutralCount }}</div>
          </div>
          <div class="overview-item">
            <div class="overview-label">看空</div>
            <div class="overview-value down">{{ bearishCount }}</div>
          </div>
          <div class="overview-item">
            <div class="overview-label">选股数量</div>
            <div class="overview-value">{{ screenerCount }}</div>
          </div>
          <div class="overview-item">
            <div class="overview-label">多策略共振</div>
            <div class="overview-value" style="color: #e6a23c;">{{ resonanceCount }}</div>
          </div>
        </div>
      </div>

      <!-- 自选股分析 -->
      <div class="card">
        <div class="card-title">📋 自选股分析</div>
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>股票</th>
                <th>现价</th>
                <th>涨跌幅</th>
                <th>综合评分</th>
                <th>技术</th>
                <th>基本面</th>
                <th>资金</th>
                <th>概念</th>
                <th>评级</th>
                <th>操作</th>
                <th>详情</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in validAnalyses" :key="item.code">
                <td>
                  <strong>{{ item.name }}</strong>
                  <div style="color: #999; font-size: 11px;">{{ item.code }}</div>
                </td>
                <td>{{ item.price }}</td>
                <td :class="getChangeClass(item.pct_change)">
                  {{ item.pct_change > 0 ? '+' : '' }}{{ formatNumber(item.pct_change) }}%
                </td>
                <td>
                  <span :class="['score-badge', getScoreClass(item.total_score)]">
                    {{ item.total_score }}
                  </span>
                </td>
                <td>{{ item.scores.technical }}</td>
                <td>{{ item.scores.fundamental }}</td>
                <td>{{ item.scores.capital }}</td>
                <td>{{ item.scores.concept }}</td>
                <td>
                  <span :class="['rating-tag', getRatingClass(item.rating)]">
                    {{ item.rating }}
                  </span>
                </td>
                <td>{{ item.action }}</td>
                <td>
                  <router-link :to="`/stock/${item.code}`">查看</router-link>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 多策略共振选股 -->
      <div v-if="resonanceStocks.length > 0" class="card">
        <div class="card-title">🔥 多策略共振选股（重点关注）</div>
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>股票</th>
                <th>现价</th>
                <th>涨跌幅</th>
                <th>命中策略</th>
                <th>策略列表</th>
                <th>均分</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in resonanceStocks" :key="item.code">
                <td>
                  <strong>{{ item.name }}</strong>
                  <div style="color: #999; font-size: 11px;">{{ item.code }}</div>
                </td>
                <td>{{ item.price }}</td>
                <td :class="getChangeClass(item.pct_change)">
                  {{ item.pct_change > 0 ? '+' : '' }}{{ formatNumber(item.pct_change) }}%
                </td>
                <td><strong>{{ item.strategy_count }}个</strong></td>
                <td style="font-size: 12px;">{{ item.strategies.join(', ') }}</td>
                <td>{{ item.avg_score }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 各策略精选 -->
      <div v-for="(results, sname) in strategyResults" :key="sname" class="card" v-if="results && results.length > 0">
        <div class="card-title">{{ strategyNames[sname] || sname }} TOP5</div>
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>股票</th>
                <th>现价</th>
                <th>涨跌幅</th>
                <th>评分</th>
                <th>理由</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in results.slice(0, 5)" :key="item.code">
                <td>
                  <strong>{{ item.name }}</strong>
                  <div style="color: #999; font-size: 11px;">{{ item.code }}</div>
                </td>
                <td>{{ item.price }}</td>
                <td :class="getChangeClass(item.pct_change)">
                  {{ item.pct_change > 0 ? '+' : '' }}{{ formatNumber(item.pct_change) }}%
                </td>
                <td>{{ item.score }}</td>
                <td style="font-size: 12px; max-width: 400px;">{{ item.reason }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { fetchLatestReport, formatNumber, getChangeClass, getScoreClass, getRatingClass } from '../utils/data'

const loading = ref(true)
const report = ref(null)

const strategyNames = {
  low_price: '💰 低价潜力股',
  technical_pattern: '📈 技术形态选股',
  capital_flow: '💹 资金面选股',
  fundamental: '📊 基本面选股',
  concept_hotspot: '🔥 概念热点选股'
}

const validAnalyses = computed(() => {
  if (!report.value) return []
  return (report.value.stock_analyses || []).filter(a => !a.error)
})

const bullishCount = computed(() => validAnalyses.value.filter(a => a.total_score >= 60).length)
const neutralCount = computed(() => validAnalyses.value.filter(a => a.total_score >= 45 && a.total_score < 60).length)
const bearishCount = computed(() => validAnalyses.value.filter(a => a.total_score < 45).length)

const screenerResult = computed(() => report.value?.screener_result || {})
const screenerCount = computed(() => screenerResult.value.combined?.length || 0)
const resonanceStocks = computed(() => (screenerResult.value.combined || []).filter(s => s.resonance))
const resonanceCount = computed(() => resonanceStocks.value.length)
const strategyResults = computed(() => screenerResult.value.strategies || {})

onMounted(async () => {
  report.value = await fetchLatestReport()
  loading.value = false
})
</script>

<style scoped>
.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 16px;
}

.overview-item {
  text-align: center;
  padding: 16px;
  background: #f8f9fb;
  border-radius: 8px;
}

.overview-label {
  font-size: 13px;
  color: #999;
  margin-bottom: 6px;
}

.overview-value {
  font-size: 24px;
  font-weight: 700;
}

.table-wrapper {
  overflow-x: auto;
}
</style>
