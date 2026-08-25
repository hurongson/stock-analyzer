#!/usr/bin/env python3
"""
本地实时监控脚本
在本地电脑运行，定时监控自选股，当买卖信号变化时推送飞书
使用方法：
  python monitor.py                  # 默认每5分钟监控一次
  python monitor.py --interval 3     # 每3分钟监控一次
  python monitor.py --stocks 600519,000001  # 指定监控股票
  python monitor.py --no-push        # 只打印不推送
"""
import os
import sys
import time
import argparse
import logging
from datetime import datetime

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import Config
from backend.data.collector import collector
from backend.analysis.engine import analyze_stock
from backend.notify.feishu import send_feishu_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("monitor")

# 记录上一次的信号状态
last_signals = {}


def is_trading_time():
    """判断当前是否为A股交易时间"""
    now = datetime.now()
    # 周末不交易
    if now.weekday() >= 5:
        return False
    # 上午 9:30-11:30
    morning_start = now.replace(hour=9, minute=30, second=0, microsecond=0)
    morning_end = now.replace(hour=11, minute=30, second=0, microsecond=0)
    # 下午 13:00-15:00
    afternoon_start = now.replace(hour=13, minute=0, second=0, microsecond=0)
    afternoon_end = now.replace(hour=15, minute=0, second=0, microsecond=0)

    if morning_start <= now <= morning_end:
        return True
    if afternoon_start <= now <= afternoon_end:
        return True
    return False


def monitor_once(stocks, enable_push=True):
    """监控一次"""
    global last_signals
    changed_stocks = []

    logger.info(f"开始监控 {len(stocks)} 只股票...")

    for code in stocks:
        try:
            result = analyze_stock(code)
            if "error" in result:
                logger.warning(f"{code} 分析失败: {result['error']}")
                continue

            ts = result.get("trading_signal", {})
            signal = ts.get("signal", "hold")
            action = ts.get("action", "观望")
            conf = ts.get("confidence", 0)
            name = result.get("name", code)
            price = result.get("price", 0)
            pct = result.get("pct_change", 0)

            # 检查信号是否变化
            last_signal = last_signals.get(code, {}).get("signal")
            signal_changed = last_signal is not None and last_signal != signal

            # 记录当前信号
            last_signals[code] = {
                "signal": signal,
                "action": action,
                "confidence": conf,
                "price": price,
                "time": datetime.now().strftime("%H:%M:%S"),
            }

            emoji = "🟩" if "买" in action else ("🟥" if "卖" in action else "⬜")
            logger.info(f"  {emoji} {name}({code}) {price}元 {pct:+.2f}% | {action} (置信度{conf}%)")

            # 信号变化且置信度足够，推送提醒
            if signal_changed and conf >= 30 and enable_push and Config.FEISHU_WEBHOOK_URL:
                changed_stocks.append(result)

        except Exception as e:
            logger.error(f"监控 {code} 异常: {e}")

    # 推送信号变化提醒
    if changed_stocks and enable_push and Config.FEISHU_WEBHOOK_URL:
        lines = [f"🔔 股票买卖信号变化提醒 ({datetime.now().strftime('%H:%M')})"]
        for r in changed_stocks:
            ts = r.get("trading_signal", {})
            emoji = "🟩" if "买" in ts.get("action", "") else "🟥"
            reasons = []
            if ts.get("buy_signals"):
                reasons.extend(ts["buy_signals"][:2])
            if ts.get("sell_signals"):
                reasons.extend(ts["sell_signals"][:2])
            reason_str = "、".join(reasons) if reasons else ""
            lines.append(
                f"{emoji} {r['name']}({r['code']}) {r['price']}元 {r['pct_change']:+.2f}%\n"
                f"   信号: {ts.get('action','')} (置信度{ts.get('confidence',0)}%)\n"
                f"   原因: {reason_str}"
            )
        lines.append("\n⚠️ 仅供参考，不构成投资建议")
        content = "\n".join(lines)
        send_feishu_text(content)
        logger.info(f"已推送 {len(changed_stocks)} 只股票信号变化提醒")

    return changed_stocks


def main():
    parser = argparse.ArgumentParser(description="本地实时股票监控")
    parser.add_argument("--interval", type=int, default=5, help="监控间隔（分钟），默认5")
    parser.add_argument("--stocks", type=str, default="", help="监控股票代码，逗号分隔（留空使用配置）")
    parser.add_argument("--no-push", action="store_true", help="不推送飞书，只打印")
    parser.add_argument("--once", action="store_true", help="只运行一次")
    args = parser.parse_args()

    stocks = [s.strip() for s in args.stocks.split(",") if s.strip()] or Config.STOCK_LIST
    enable_push = not args.no_push

    print("=" * 60)
    print("📈 本地实时股票监控系统")
    print(f"   监控股票: {stocks}")
    print(f"   监控间隔: {args.interval} 分钟")
    print(f"   飞书推送: {'开启' if enable_push and Config.FEISHU_WEBHOOK_URL else '关闭'}")
    print("=" * 60)

    if args.once:
        monitor_once(stocks, enable_push)
        return

    # 持续监控
    while True:
        try:
            if is_trading_time():
                monitor_once(stocks, enable_push)
            else:
                logger.info("非交易时间，等待中...")

            # 等待下一次监控
            logger.info(f"等待 {args.interval} 分钟后再次监控...")
            time.sleep(args.interval * 60)

        except KeyboardInterrupt:
            logger.info("监控已停止")
            break
        except Exception as e:
            logger.error(f"监控异常: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
