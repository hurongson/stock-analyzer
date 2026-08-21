<template>
  <div class="app-container">
    <header class="app-header">
      <h1>📈 股票分析系统</h1>
      <nav class="nav">
        <router-link to="/">分析看板</router-link>
        <router-link to="/screener">选股结果</router-link>
        <router-link to="/history">历史报告</router-link>
      </nav>
    </header>
    <main class="app-main">
      <router-view />
    </main>
    <footer class="app-footer">
      数据来源：AKShare | 分析结果仅供参考，不构成投资建议 | 投资有风险，入市需谨慎
    </footer>
  </div>
</template>

<script setup>
</script>
