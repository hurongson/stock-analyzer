@echo off
chcp 65001 >nul
REM ============================================================
REM 股票分析系统 - 统一启动脚本 (Windows)
REM 使用方法: 双击 start.bat
REM ============================================================

cd /d "%~dp0backend"

:menu
cls
echo ========================================
echo   📈 股票分析系统 - 模式选择
echo ========================================
echo.
echo   [1] 云端定时模式（推荐，零成本）
echo       GitHub Actions 自动运行，飞书推送
echo       无需本地电脑常开
echo.
echo   [2] 本地实时监控模式
echo       每5分钟监控自选股，信号变化推送飞书
echo       需要本地电脑常开
echo.
echo   [3] 本地快速分析一次
echo       立即分析自选股，输出买卖信号
echo.
echo   [4] 本地完整分析一次
echo       自选股+选股+深度报告
echo.
echo   [5] 查看配置
echo.
echo   [0] 退出
echo.
echo ========================================
set /p choice=请选择模式 [0-5]: 

if "%choice%"=="1" goto cloud
if "%choice%"=="2" goto local_monitor
if "%choice%"=="3" goto quick
if "%choice%"=="4" goto full
if "%choice%"=="5" goto config
if "%choice%"=="0" goto exit
goto menu

:cloud
cls
echo.
echo 📋 云端定时模式配置说明：
echo.
echo 1. 打开 GitHub 仓库: https://github.com/hurongson/stock-analyzer
echo 2. 进入 Settings → Secrets and variables → Actions
echo 3. 添加以下 Secrets：
echo    - TUSHARE_TOKEN: 你的 Tushare Token
echo    - FEISHU_WEBHOOK_URL: 飞书机器人 Webhook 地址
echo    - FEISHU_SECRET: 飞书签名密钥（可选）
echo    - STOCK_LIST: 自选股代码，逗号分隔（如 600519,000001）
echo    - ENABLE_CLOUD_MONITOR: true（设为 false 可关闭云端模式）
echo.
echo 4. 配置完成后，每个工作日交易时段自动运行：
echo    9:45 / 10:30 / 11:15 / 13:30 / 14:00 快速分析
echo    14:45 完整分析（含选股）
echo.
echo 💡 切换到本地模式：将 ENABLE_CLOUD_MONITOR 设为 false
echo.
pause
goto menu

:local_monitor
cls
set /p interval=监控间隔（分钟，默认5）: 
if "%interval%"=="" set interval=5
echo.
echo 🚀 启动本地实时监控，间隔 %interval% 分钟...
echo    按 Ctrl+C 停止
echo.
python monitor.py --interval %interval%
pause
goto menu

:quick
cls
echo 🚀 运行快速分析...
echo.
python main.py --quick --force
echo.
pause
goto menu

:full
cls
echo 🚀 运行完整分析...
echo.
python main.py --force
echo.
pause
goto menu

:config
cls
echo 📝 当前配置文件: backend\.env
echo.
if exist .env (
    type .env
) else (
    echo （.env 文件不存在，使用默认配置）
    echo.
    echo 可配置项：
    echo   TUSHARE_TOKEN=你的token
    echo   FEISHU_WEBHOOK_URL=飞书webhook
    echo   FEISHU_SECRET=飞书密钥
    echo   STOCK_LIST=600519,000001
    echo   LOW_PRICE_THRESHOLD=10
)
echo.
pause
goto menu

:exit
echo 再见！
exit /b 0
