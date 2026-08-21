# 📈 股票分析系统

基于 Python + Vue3 + GitHub Actions 的零成本 A 股智能分析系统。每日自动选股、五维分析、LLM 深度解读，飞书推送，前端可视化展示。

## ✨ 功能特性

- **五维分析引擎**：技术面 / 基本面 / 资金面 / 概念热点 / LLM 深度分析，综合评分 0-100
- **五大选股策略**：低价潜力 / 技术形态 / 资金流入 / 基本面优选 / 概念热点，支持多策略共振
- **零成本部署**：GitHub Actions 定时运行，结果存仓库 JSON，Vue3 静态页 GitHub Pages 展示
- **飞书推送**：每日收盘后自动推送分析卡片到飞书群
- **LLM 增强**：集成 DeepSeek / 通义千问等 OpenAI 兼容接口，AI 深度解读
- **专业前端**：Vue3 + ECharts，五维雷达图、评分看板、选股筛选

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────┐
│  GitHub Actions（每日 18:00 北京时间自动运行）    │
│  ┌───────────┐  ┌──────────┐  ┌──────────────┐ │
│  │ 数据采集   │→│ 分析引擎  │→│ 报告生成      │ │
│  │ (akshare) │  │ 五维+LLM │  │ JSON+Markdown│ │
│  └───────────┘  └──────────┘  └──────┬───────┘ │
│                                      ↓         │
│  ┌───────────┐  ┌──────────┐  ┌──────────────┐ │
│  │ 飞书推送   │  │ 提交仓库  │  │ GitHub Pages │ │
│  │ (Webhook) │  │ (git)    │  │ (Vue3 前端)  │ │
│  └───────────┘  └──────────┘  └──────────────┘ │
└─────────────────────────────────────────────────┘
```

## 📁 项目结构

```
stock-analyzer/
├── backend/                    # Python 后端
│   ├── main.py                 # 主入口
│   ├── config.py               # 配置管理
│   ├── requirements.txt        # 依赖
│   ├── data/                   # 数据采集层
│   │   ├── collector.py        # akshare 封装
│   │   └── cache.py            # 本地缓存
│   ├── analysis/               # 分析引擎
│   │   ├── engine.py           # 五维综合入口
│   │   ├── indicators.py       # 技术指标计算
│   │   ├── technical.py        # 技术面分析
│   │   ├── fundamental.py      # 基本面分析
│   │   ├── capital_flow.py     # 资金面分析
│   │   ├── concept.py          # 概念热点分析
│   │   └── llm_analyzer.py     # LLM 深度分析
│   ├── screener/               # 选股引擎
│   │   ├── engine.py           # 选股调度
│   │   └── strategies/         # 五大策略
│   │       ├── low_price.py
│   │       ├── technical_pattern.py
│   │       ├── capital_flow.py
│   │       ├── fundamental.py
│   │       └── concept_hotspot.py
│   ├── report/                 # 报告生成
│   │   └── generator.py
│   ├── notify/                 # 推送
│   │   └── feishu.py
│   └── utils/                  # 工具函数
├── frontend/                   # Vue3 前端
│   ├── src/
│   │   ├── views/              # 页面
│   │   │   ├── Dashboard.vue   # 分析看板
│   │   │   ├── StockDetail.vue # 个股详情
│   │   │   ├── Screener.vue    # 选股结果
│   │   │   └── History.vue     # 历史报告
│   │   ├── router/             # 路由
│   │   ├── utils/              # 工具
│   │   └── assets/             # 样式
│   ├── package.json
│   ├── vite.config.js
│   └── index.html
├── .github/workflows/
│   └── daily-analysis.yml      # GitHub Actions 定时任务
├── data/                       # 运行时数据（自动生成）
├── docs/                       # 文档
├── .env.example                # 配置模板
└── .gitignore
```

## 🚀 快速开始

### 方式一：零成本部署（推荐）

1. **Fork 本仓库**到你的 GitHub
2. **配置 Secrets**：仓库 Settings → Secrets and variables → Actions，添加以下变量：
   - `STOCK_LIST`：自选股代码，逗号分隔（如 `600519,000001`）
   - `LLM_API_KEY`：LLM API Key（DeepSeek/通义千问等）
   - `LLM_BASE_URL`：API 地址（默认 `https://api.deepseek.com/v1`）
   - `LLM_MODEL`：模型名（默认 `deepseek-chat`）
   - `FEISHU_WEBHOOK_URL`：飞书机器人 Webhook 地址
   - `FEISHU_SECRET`：飞书签名密钥（可选）
3. **启用 GitHub Pages**：Settings → Pages → Source 选择 "GitHub Actions"
4. **手动触发**：Actions → 每日股票分析 → Run workflow，验证是否正常
5. **自动运行**：每个工作日北京时间 18:00 自动执行

### 方式二：本地运行

```bash
# 1. 安装后端依赖
cd backend
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example ../.env
# 编辑 .env 填入你的配置

# 3. 运行分析
python main.py --force --no-llm    # 不使用 LLM 快速测试
python main.py --force              # 完整分析（含 LLM）
python main.py --analyze 600519    # 分析单只股票
python main.py --screener           # 仅运行选股

# 4. 启动前端
cd ../frontend
npm install
npm run dev
# 访问 http://localhost:5173
```

## 📊 评分体系

### 五维权重
| 维度 | 权重 | 说明 |
|------|------|------|
| 技术面 | 30% | 趋势/MACD/RSI/KDJ/布林/量能 |
| 基本面 | 25% | PE/PB/ROE/营收增长/净利润增长 |
| 资金面 | 20% | 主力净流入/大单结构/5日趋势 |
| 概念热点 | 15% | 热门概念匹配/板块涨幅 |
| LLM 综合 | 10% | AI 深度解读调整 |

### 综合评级
| 评分 | 评级 | 操作建议 |
|------|------|----------|
| ≥75 | 强烈看多 | 买入 |
| 60-74 | 偏多 | 逢低关注 |
| 45-59 | 中性 | 观望 |
| 30-44 | 偏空 | 减仓 |
| <30 | 强烈看空 | 卖出 |

## 🎯 选股策略

1. **低价潜力股**：低价 + 小市值 + 基本面尚可 + 技术企稳
2. **技术形态选股**：均线多头 / 放量突破 / MACD金叉 / KDJ超卖 / 平台突破
3. **资金面选股**：主力持续流入 + 大单净流入 + 量价配合
4. **基本面选股**：低估值 + 高ROE + 业绩增长 + 合理市值
5. **概念热点选股**：热门概念领涨 + 概念叠加 + 资金认可

多策略同时命中的股票标记为"共振"，优先级最高。

## 🔧 技术栈

| 层级 | 技术 |
|------|------|
| 后端语言 | Python 3.11+ |
| 数据源 | AKShare（免费 A 股数据） |
| 技术指标 | pandas-ta / 纯 pandas 实现 |
| LLM | OpenAI 兼容接口（DeepSeek/通义千问等） |
| 推送 | 飞书 Webhook 机器人 |
| 前端 | Vue 3 + Vite + Vue Router |
| 图表 | ECharts 5 |
| 部署 | GitHub Actions + GitHub Pages |

## ⚠️ 免责声明

本系统仅供学习和研究使用，分析结果由算法自动生成，**不构成任何投资建议**。股市有风险，投资需谨慎。使用者应自行判断并承担投资风险。

## 📄 License

MIT
