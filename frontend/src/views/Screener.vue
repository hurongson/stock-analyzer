<template>
  <div>
    <div v-if="loading" class="loading">
      <div class="loading-spinner"></div>
      <p>加载选股结果...</p>
    </div>

    <div v-else-if="!screenerData" class="card">
      <p>暂无选股数据。</p>
    </div>

    <template v-else>
      <!-- 策略筛选标签 -->
      <div class="card">
        <div class="card-title">🎯 选股结果</div>
        <div class="filter-tabs">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            :class="['tab-btn', { active: activeTab === tab.key }]"
            @click="activeTab = tab.key"
          >
            {{ tab.label }}
            <span class="tab-count">{{ tab.count }}</span>
          </button>
        </div>
      </div>

      <!-- 综合排序结果 -->
      <div v-if="activeTab === 'combined'" class="card">
        <div class="card-title">综合排序（多策略共振优先）</div>
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>股票</th>
                <th>现价</th>
                <th>涨跌幅</th>
                <th>命中策略</th>
                <th>策略列表</th>
                <th>均分</th>
                <th>共振</th>
                <th>详情</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, idx) in combinedList" :key="item.code">
                <td>{{ idx + 1 }}</td>
                <td>
                  <strong>{{ item.name }}</strong>
                  <div style="color: #999; font-size: 11px;">{{ item.code }}</div>
                </td>
                <td>{{ item.price }}</td>
                <td :class="getChangeClass(item.pct_change)">
                  {{ item.pct_change > 0 ? '+' : '' }}{{ formatNumber(item.pct_change) }}%
                </td>
                <td><strong>{{ item.strategy_count }}</strong></td>
                <td style="font-size: 12px;">
                  <span v-for="s in item.strategies" :key="s" class="strategy-tag">
                    {{ strategyShort[s] || s }}
                  </span>
                </td>
                <td>{{ item.avg_score }}</td>
                <td>
                  <span v-if="item.resonance" style="color: #e6a23c; font-weight: 600;">🔥 共振</span>
                  <span v-else style="color: #ccc;">-</span>
                </td>
                <td>
                  <router-link :to="`/stock/${item.code}`">查看</router-link>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 各策略详情 -->
      <div v-else class="card">
        <div class="card-title">{{ strategyNames[activeTab] }}</div>
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>股票</th>
                <th>现价</th>
                <th>涨跌幅</th>
                <th>评分</th>
                <th>入选理由</th>
                <th>详情</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, idx) in currentStrategyList" :key="item.code">
                <td>{{ idx + 1 }}</td>
                <td>
                  <strong>{{ item.name }}</strong>
                  <div style="color: #999; font-size: 11px;">{{ item.code }}</div>
                </td>
                <td>{{ item.price }}</td>
                <td :class="getChangeClass(item.pct_change)">
                  {{ item.pct_change > 0 ? '+' : '' }}{{ formatNumber(item.pct_change) }}%
                </td>
                <td>
                  <span :class="['score-badge', getScoreClass(item.score)]">{{ item.score }}</span>
                </td>
                <td style="font-size: 12px; max-width: 400px;">{{ item.reason }}</td>
                <td>
                  <router-link :to="`/stock/${item.code}`">查看</router-link>
                </td>
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
import { fetchLatestReport, formatNumber, getChangeClass, getScoreClass } from '../utils/data'

const loading = ref(true)
const screenerData = ref(null)
const activeTab = ref('combined')

const strategyNames = {
  low_price: '💰 低价潜力股',
  technical_pattern: '📈 技术形态选股',
  capital_flow: '💹 资金面选股',
  fundamental: '📊 基本面选股',
  concept_hotspot: '🔥 概念热点选股'
}

const strategyShort = {
  low_price: '低价',
  technical_pattern: '技术',
  capital_flow: '资金',
  fundamental: '基本面',
  concept_hotspot: '概念'
}

const combinedList = computed(() => screenerData.value?.combined || [])
const currentStrategyList = computed(() => {
  if (!screenerData.value?.strategies) return []
  return screenerData.value.strategies[activeTab.value] || []
})

const tabs = computed(() => {
  const list = [{ key: 'combined', label: '综合排序', count: combinedList.value.length }]
  const strategies = screenerData.value?.strategies || {}
  for (const [key, results] of Object.entries(strategies)) {
    list.push({
      key,
      label: strategyShort[key] || key,
      count: results.length
    })
  }
  return list
})

onMounted(async () => {
  const report = await fetchLatestReport()
  screenerData.value = report?.screener_result || null
  loading.value = false
})
</script>

<style scoped>
.filter-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.tab-btn {
  padding: 8px 16px;
  border: 1px solid #e0e0e0;
  background: #fff;
  border-radius: 20px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}

.tab-btn:hover {
  border-color: #409eff;
  color: #409eff;
}

.tab-btn.active {
  background: #409eff;
  color: #fff;
  border-color: #409eff;
}

.tab-count {
  margin-left: 4px;
  font-size: 11px;
  opacity: 0.8;
}

.strategy-tag {
  display: inline-block;
  padding: 1px 6px;
  background: #ecf5ff;
  color: #409eff;
  border-radius: 3px;
  margin-right: 4px;
  font-size: 11px;
}

.table-wrapper {
  overflow-x: auto;
}
</style>
