# 开发指南

## 代码架构

### 后端分层

```
backend/
├── main.py              # 入口，命令行参数解析，流程编排
├── config.py            # 全局配置（环境变量读取）
├── data/                # 数据层
│   ├── collector.py     # akshare 封装，统一数据格式
│   └── cache.py         # 按天文件缓存
├── analysis/            # 分析层
│   ├── engine.py        # 五维综合分析入口
│   ├── indicators.py    # 技术指标计算（纯 pandas 实现）
│   ├── technical.py     # 技术面分析
│   ├── fundamental.py   # 基本面分析
│   ├── capital_flow.py  # 资金面分析
│   ├── concept.py       # 概念热点分析
│   └── llm_analyzer.py  # LLM 深度分析
├── screener/            # 选股层
│   ├── engine.py        # 选股调度，多策略合并
│   └── strategies/      # 具体策略
├── report/              # 报告层
│   └── generator.py     # JSON + Markdown 报告生成
├── notify/              # 推送层
│   └── feishu.py        # 飞书 Webhook 推送
└── utils/               # 工具层
    └── helpers.py       # 通用函数
```

### 前端结构

```
frontend/src/
├── main.js              # 入口
├── App.vue              # 根组件（导航栏 + 路由出口）
├── router/index.js      # 路由配置
├── views/               # 页面组件
│   ├── Dashboard.vue    # 首页看板
│   ├── StockDetail.vue  # 个股详情（雷达图）
│   ├── Screener.vue     # 选股结果
│   └── History.vue      # 历史报告
├── utils/data.js        # 数据获取 + 格式化工具
└── assets/main.css      # 全局样式
```

## 核心数据流

```
1. main.py 调用 screener.run_all()
   → collector.get_all_stocks() 获取全量股票
   → 各策略 screen() 逐只筛选
   → engine._merge_results() 合并去重，共振加分

2. main.py 调用 analyze_batch(stock_list)
   → 每只股票 analyze_stock()
   → 分别调用 technical/fundamental/capital/concept 分析
   → llm_deep_analyze() 可选 LLM 深度分析
   → 加权计算 total_score，映射评级

3. generate_daily_report() 生成 JSON + Markdown
   → 保存到 data/reports/report_YYYY-MM-DD.json
   → 同时保存 data/latest.json（前端读取）

4. push_daily_report() 推送飞书卡片

5. GitHub Actions commit 结果到仓库
   → 前端构建时将 data/ 复制到 dist/
   → GitHub Pages 部署，前端 fetch ./data/latest.json
```

## 添加新的选股策略

### 1. 创建策略文件

`backend/screener/strategies/my_strategy.py`:

```python
import pandas as pd
from typing import List, Dict
from backend.screener.strategies.base import BaseStrategy

class MyStrategy(BaseStrategy):
    name = "my_strategy"
    description = "我的自定义策略"

    def screen(self, df: pd.DataFrame, **kwargs) -> List[Dict]:
        results = []
        # df 是全量股票列表，包含 code/name/price/pct_change/amount/turnover/pe/pb/total_mv 等字段
        filtered = df[
            (df["price"] > 0) &
            (df["pct_change"] > 3) &
            (df["amount"] > 1e8)
        ]

        for _, row in filtered.iterrows():
            score = 60  # 自定义评分逻辑
            reasons = ["涨幅>3%", "成交额>1亿"]
            results.append(self._make_result(row, "；".join(reasons), score))

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:20]
```

### 2. 注册策略

在 `backend/screener/engine.py` 的 `__init__` 中添加：

```python
from backend.screener.strategies.my_strategy import MyStrategy

self.strategies = {
    # ... 现有策略
    "my_strategy": MyStrategy(),
}
```

### 3. 前端添加名称映射

在 `Dashboard.vue` 和 `Screener.vue` 的 `strategyNames` 中添加：

```js
const strategyNames = {
  // ... 现有
  my_strategy: '🎯 我的策略'
}
```

## 添加新的分析维度

### 1. 创建分析模块

`backend/analysis/my_dimension.py`:

```python
from typing import Dict
from backend.data.collector import collector

def analyze_my_dimension(code: str) -> Dict:
    # 获取数据，计算评分，生成结论
    return {
        "score": 60,
        "conclusions": ["结论1", "结论2"],
        "data": {...}
    }
```

### 2. 集成到分析引擎

在 `backend/analysis/engine.py` 中：
- 导入新模块
- 在 `analyze_stock()` 中调用
- 在 `WEIGHTS` 中添加权重
- 在 `scores` 字典中添加评分
- 调整权重使总和为 1

### 3. 前端展示

在 `StockDetail.vue` 中添加对应的卡片展示。

## 技术指标扩展

`backend/analysis/indicators.py` 中已实现常用指标。如需添加：

```python
def calc_my_indicator(close: pd.Series, period: int = 14) -> Dict:
    # 计算逻辑
    return {"value": ..., "signal": ...}
```

然后在 `analyze_technicals()` 中调用，并在 `calc_technical_score()` 中加入评分逻辑。

## 数据源扩展

当前使用 akshare 作为主数据源。如需添加 tushare 等：

1. 在 `backend/data/collector.py` 中添加新的数据源方法
2. 使用统一的返回格式（DataFrame 或 Dict）
3. 在 `config.py` 中添加对应的 Token 配置
4. 可选实现 fallback 机制（akshare 失败时用 tushare）

## 测试

```bash
# 测试单只股票分析（不使用 LLM，快速验证）
cd backend
python main.py --analyze 600519 --no-llm --force

# 测试选股
python main.py --screener --force

# 完整测试
python main.py --force --no-push
```

## 注意事项

1. **akshare 接口稳定性**：akshare 依赖第三方网站，接口可能随上游变动。如遇报错，先升级 akshare 版本：`pip install --upgrade akshare`
2. **请求频率**：选股时逐只请求数据，注意不要过于频繁。已实现按天缓存。
3. **GitHub Actions 限制**：免费账户每月 2000 分钟（公开仓库无限），单次运行建议控制在 15 分钟内。
4. **LLM 费用**：批量分析多只股票时 token 消耗较大，建议控制自选股数量（5-10 只）。
5. **数据时效**：所有数据仅供参考，实际交易请以交易所数据为准。
