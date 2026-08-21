# 部署指南

## 零成本部署（GitHub Actions + GitHub Pages）

### 1. Fork 仓库

将本仓库 Fork 到你自己的 GitHub 账号下。

### 2. 配置 Secrets

进入仓库 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

逐个添加以下配置：

| Secret 名称 | 必填 | 说明 | 示例 |
|------------|------|------|------|
| `STOCK_LIST` | 否 | 自选股代码，逗号分隔 | `600519,000001,300750` |
| `LLM_API_KEY` | 是* | LLM API Key | `sk-xxxxxxxx` |
| `LLM_BASE_URL` | 否 | API 地址 | `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 否 | 模型名称 | `deepseek-chat` |
| `FEISHU_WEBHOOK_URL` | 否 | 飞书机器人地址 | `https://open.feishu.cn/open-apis/bot/v2/hook/xxx` |
| `FEISHU_SECRET` | 否 | 飞书签名密钥 | `xxxxxxxx` |
| `TUSHARE_TOKEN` | 否 | Tushare Token（增强数据） | `xxxxxxxx` |
| `LOW_PRICE_THRESHOLD` | 否 | 低价股价格上限 | `15` |
| `SCREENER_MAX_RESULTS` | 否 | 选股数量上限 | `50` |

> *LLM_API_KEY 可选，不填则自动禁用 LLM 深度分析，其他功能正常。

### 3. 获取 LLM API Key

#### DeepSeek（推荐，便宜好用）
1. 访问 https://platform.deepseek.com/
2. 注册账号，充值（最低 10 元）
3. API Keys → Create API Key
4. 复制 Key 填入 `LLM_API_KEY`
5. `LLM_BASE_URL` 填 `https://api.deepseek.com/v1`
6. `LLM_MODEL` 填 `deepseek-chat`

#### 通义千问
1. 访问 https://dashscope.console.aliyun.com/
2. 开通 DashScope，获取 API Key
3. `LLM_BASE_URL` 填 `https://dashscope.aliyuncs.com/compatible-mode/v1`
4. `LLM_MODEL` 填 `qwen-plus` 或 `qwen-turbo`

#### 其他 OpenAI 兼容接口
任何支持 OpenAI 格式的接口都可以使用，填入对应的 BASE_URL 和 MODEL 即可。

### 4. 创建飞书机器人

1. 打开飞书，进入目标群聊
2. 群设置 → 群机器人 → 添加机器人 → 自定义机器人
3. 填写机器人名称（如"股票分析助手"），描述
4. 安全设置：建议勾选"签名校验"，复制签名密钥
5. 创建后复制 Webhook 地址
6. 将 Webhook 地址填入 `FEISHU_WEBHOOK_URL`
7. 签名密钥填入 `FEISHU_SECRET`（如果启用了签名校验）

### 5. 启用 GitHub Pages

1. 仓库 → **Settings** → **Pages**
2. **Source** 选择 **GitHub Actions**
3. 保存

### 6. 手动触发测试

1. 仓库 → **Actions** → 选择"每日股票分析"
2. 点击 **Run workflow**
3. 可选输入自选股代码和是否禁用 LLM
4. 点击 **Run workflow** 开始执行
5. 等待运行完成（约 5-15 分钟）
6. 检查：
   - Actions 运行日志是否成功
   - 仓库 `data/` 目录是否生成了 `latest.json`
   - 飞书群是否收到推送
   - GitHub Pages 地址是否可访问

### 7. 自动运行

配置完成后，系统会在**每个工作日北京时间 18:00**（收盘后）自动运行：
- UTC 时间 10:00 = 北京时间 18:00
- 仅周一至周五运行
- 如需调整时间，修改 `.github/workflows/daily-analysis.yml` 中的 cron 表达式

## 本地部署

### 环境要求
- Python 3.10+
- Node.js 16+
- pip

### 后端

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 配置
cp ../.env.example ../.env
# 编辑 .env

# 运行
python main.py --force --no-llm   # 快速测试
python main.py --force            # 完整运行
```

### 前端

```bash
cd frontend
npm install
npm run dev    # 开发模式
npm run build  # 构建生产版本
```

前端开发模式下，需要先运行后端生成 `data/latest.json`，然后将 `data` 目录复制到 `frontend/public/` 下，或者配置 Vite 代理。

## 常见问题

### Q: Actions 运行失败怎么办？
A: 进入 Actions 运行详情，查看具体步骤的日志输出。常见原因：
- Secrets 未配置或配置错误
- akshare 接口变动（升级 akshare 版本）
- GitHub API 限流（减少选股数量）

### Q: 飞书收不到消息？
A: 检查：
- Webhook 地址是否正确
- 签名密钥是否匹配（如果启用了签名）
- 机器人是否还在群内
- 飞书机器人频率限制（每分钟 20 条）

### Q: 前端页面空白？
A: 检查：
- GitHub Pages 是否已启用
- Actions 是否成功构建并部署了前端
- `data/latest.json` 是否存在
- 浏览器控制台是否有报错

### Q: 选股运行时间太长？
A: 技术形态和资金面策略会逐只请求数据，200 只可能耗时较长。可以：
- 减少 `SCREENER_MAX_RESULTS`
- 修改策略中的 `candidates.head(200)` 为更小的值
- 增加 Actions timeout（当前 30 分钟）

### Q: 如何添加新的选股策略？
A: 
1. 在 `backend/screener/strategies/` 下新建策略文件，继承 `BaseStrategy`
2. 实现 `screen()` 方法
3. 在 `backend/screener/engine.py` 的 `__init__` 中注册新策略
4. 前端 `Dashboard.vue` 和 `Screener.vue` 中添加策略名称映射
