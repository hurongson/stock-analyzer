<template>
  <div>
    <div class="card">
      <div class="card-title">📅 历史报告</div>
      <p style="color: #999; font-size: 13px;">
        历史报告由 GitHub Actions 每日自动生成并提交到仓库。以下为最近的报告列表。
      </p>
    </div>

    <div class="card">
      <div class="card-title">报告列表</div>
      <div v-if="reports.length === 0" class="loading">
        <p>暂无历史报告（首次运行后将自动生成）</p>
      </div>
      <div v-else class="report-list">
        <div v-for="r in reports" :key="r.date" class="report-item" @click="viewReport(r.date)">
          <div class="report-date">📆 {{ r.date }}</div>
          <div class="report-meta">
            <span>自选股: {{ r.stockCount }}只</span>
            <span>选股: {{ r.screenerCount }}只</span>
          </div>
          <div class="report-arrow">›</div>
        </div>
      </div>
    </div>

    <!-- 报告详情弹窗 -->
    <div v-if="selectedReport" class="modal-overlay" @click.self="selectedReport = null">
      <div class="modal-content">
        <div class="modal-header">
          <h3>📊 {{ selectedDate }} 分析报告</h3>
          <button class="close-btn" @click="selectedReport = null">✕</button>
        </div>
        <div class="modal-body">
          <div v-html="formattedMarkdown"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { fetchLatestReport, fetchReportByDate } from '../utils/data'

const reports = ref([])
const selectedReport = ref(null)
const selectedDate = ref('')

const formattedMarkdown = computed(() => {
  if (!selectedReport.value?.markdown) return ''
  // 简单的 Markdown 渲染（替换标题、列表、表格等）
  let md = selectedReport.value.markdown
  md = md.replace(/^### (.*$)/gm, '<h4>$1</h4>')
  md = md.replace(/^## (.*$)/gm, '<h3>$1</h3>')
  md = md.replace(/^# (.*$)/gm, '<h2>$1</h2>')
  md = md.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
  md = md.replace(/^- (.*$)/gm, '<li>$1</li>')
  md = md.replace(/(<li>.*<\/li>\n?)+/g, m => `<ul>${m}</ul>`)
  md = md.replace(/\n/g, '<br>')
  return md
})

async function viewReport(date) {
  selectedDate.value = date
  selectedReport.value = await fetchReportByDate(date)
}

onMounted(async () => {
  // 从最新报告中获取日期，同时尝试加载最近几天的报告
  const latest = await fetchLatestReport()
  if (latest) {
    reports.value.push({
      date: latest.date,
      stockCount: (latest.stock_analyses || []).filter(a => !a.error).length,
      screenerCount: latest.screener_result?.combined?.length || 0
    })
  }

  // 尝试加载最近10个工作日的报告
  const today = new Date()
  for (let i = 1; i <= 15; i++) {
    const d = new Date(today)
    d.setDate(d.getDate() - i)
    if (d.getDay() === 0 || d.getDay() === 6) continue // 跳过周末
    const dateStr = d.toISOString().split('T')[0]
    if (reports.value.some(r => r.date === dateStr)) continue
    const r = await fetchReportByDate(dateStr)
    if (r) {
      reports.value.push({
        date: dateStr,
        stockCount: (r.stock_analyses || []).filter(a => !a.error).length,
        screenerCount: r.screener_result?.combined?.length || 0
      })
    }
  }
  reports.value.sort((a, b) => b.date.localeCompare(a.date))
})
</script>

<style scoped>
.report-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.report-item {
  display: flex;
  align-items: center;
  padding: 14px 16px;
  background: #f8f9fb;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}

.report-item:hover {
  background: #ecf5ff;
}

.report-date {
  font-size: 15px;
  font-weight: 600;
  flex: 1;
}

.report-meta {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: #666;
}

.report-arrow {
  font-size: 20px;
  color: #ccc;
  margin-left: 12px;
}

.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.modal-content {
  background: #fff;
  border-radius: 12px;
  width: 100%;
  max-width: 800px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #eee;
}

.modal-header h3 {
  margin: 0;
}

.close-btn {
  background: none;
  border: none;
  font-size: 18px;
  cursor: pointer;
  color: #999;
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
  font-size: 14px;
  line-height: 1.8;
}

.modal-body :deep(h2) { font-size: 20px; margin: 16px 0 12px; }
.modal-body :deep(h3) { font-size: 17px; margin: 14px 0 10px; }
.modal-body :deep(h4) { font-size: 15px; margin: 12px 0 8px; }
.modal-body :deep(ul) { padding-left: 20px; margin: 8px 0; }
.modal-body :deep(li) { margin: 4px 0; }
.modal-body :deep(table) { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 13px; }
.modal-body :deep(th), .modal-body :deep(td) { border: 1px solid #e0e0e0; padding: 6px 10px; text-align: left; }
.modal-body :deep(th) { background: #f5f7fa; }
</style>
