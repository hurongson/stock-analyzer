#!/usr/bin/env python3
"""
股票分析系统 - 主入口
支持命令行参数：
  python main.py                  # 完整运行：选股 + 自选股分析 + 报告 + 推送
  python main.py --analyze 600519,000001  # 分析指定股票
  python main.py --screener       # 仅运行选股
  python main.py --no-push        # 不推送飞书
  python main.py --no-llm         # 禁用 LLM
  python main.py --dry-run        # 试运行（不保存、不推送）
"""
import sys
import os
import argparse
import logging

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import Config
from backend.utils.helpers import is_trading_day, today_str
from backend.analysis.engine import analyze_stock, analyze_batch
from backend.analysis.market_timing import market_timing_instance
from backend.screener.engine import screener
from backend.screener.late_day import late_day_screener
from backend.report.generator import generate_daily_report, save_report
from backend.notify.feishu import push_daily_report, send_feishu_text, push_late_day_picks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("main")


def run_quick_analysis(stocks: list = None, enable_push: bool = True):
    """
    快速分析模式（盘中使用）
    只分析自选股，不跑选股，禁用LLM，重点输出交易信号，速度快
    """
    Config.ensure_dirs()
    Config.ENABLE_LLM = False  # 快速模式禁用LLM
    stock_list = stocks or Config.STOCK_LIST
    logger.info(f"===== 快速盘中分析 =====")
    logger.info(f"自选股: {stock_list}")

    # 只分析自选股
    try:
        stock_analyses = analyze_batch(stock_list)
        logger.info(f"完成 {len(stock_analyses)} 只股票分析")
    except Exception as e:
        logger.error(f"自选股分析失败: {e}")
        stock_analyses = []

    # 生成简洁报告（不含选股）
    report = generate_daily_report(stock_analyses, None)

    # 保存 latest.json 供前端读取
    latest_path = os.path.join(Config.DATA_DIR, "latest.json")
    from backend.utils.helpers import save_json
    save_json(report["json"], latest_path)
    logger.info(f"最新报告已保存: {latest_path}")

    # 推送飞书（简洁版，重点买卖信号）
    if enable_push and Config.FEISHU_WEBHOOK_URL:
        logger.info("--- 推送飞书买卖信号 ---")
        push_daily_report(report["json"])
    else:
        logger.info("跳过飞书推送（未配置 Webhook 或禁用推送）")

    # 控制台输出买卖信号
    print("\n" + "="*60)
    print(f"📊 盘中快速分析 - {today_str()}")
    print("="*60)
    for r in stock_analyses:
        if "error" in r:
            print(f"\n❌ {r.get('code','')} 分析失败: {r['error']}")
            continue
        ts = r.get("trading_signal", {})
        signal = ts.get("action", "观望")
        conf = ts.get("confidence", 0)
        emoji = "🟩" if "买" in signal else ("🟥" if "卖" in signal else "⬜")
        print(f"\n{emoji} {r['name']}({r['code']}) {r['price']}元 {r['pct_change']:+.2f}%")
        print(f"   信号: {signal} (置信度{conf}%)")
        if ts.get("buy_signals"):
            print(f"   买入理由: {', '.join(ts['buy_signals'][:3])}")
        if ts.get("sell_signals"):
            print(f"   卖出理由: {', '.join(ts['sell_signals'][:3])}")
    print("\n" + "="*60)

    logger.info("===== 快速分析完成 =====")
    return report


def run_full_analysis(stocks: list = None, enable_push: bool = True, enable_llm: bool = None):
    """运行完整分析流程"""
    Config.ensure_dirs()

    if enable_llm is not None:
        Config.ENABLE_LLM = enable_llm

    stock_list = stocks or Config.STOCK_LIST
    logger.info(f"===== 开始每日股票分析 =====")
    logger.info(f"自选股: {stock_list}")
    logger.info(f"LLM 分析: {'开启' if Config.ENABLE_LLM else '关闭'}")

    # 0. 市场择时
    logger.info("--- 步骤0: 市场择时分析 ---")
    try:
        market_timing_result = market_timing_instance.analyze()
        logger.info(f"市场情绪: {market_timing_result.get('sentiment')}({market_timing_result.get('sentiment_score')}分), 建议仓位{market_timing_result.get('position')}")
    except Exception as e:
        logger.error(f"市场择时失败: {e}")
        market_timing_result = None

    # 1. 选股
    logger.info("--- 步骤1: 运行选股引擎 ---")
    try:
        screener_result = screener.run_all()
        logger.info(f"选股完成，共选出 {screener_result.get('summary', {}).get('combined_count', 0)} 只")
    except Exception as e:
        logger.error(f"选股失败: {e}")
        screener_result = None

    # 2. 自选股分析
    logger.info("--- 步骤2: 自选股分析 ---")
    try:
        stock_analyses = analyze_batch(stock_list)
        logger.info(f"完成 {len(stock_analyses)} 只股票分析")
    except Exception as e:
        logger.error(f"自选股分析失败: {e}")
        stock_analyses = []

    # 3. 生成报告
    logger.info("--- 步骤3: 生成报告 ---")
    report = generate_daily_report(stock_analyses, screener_result)
    # 添加市场择时结果
    if market_timing_result:
        report["json"]["market_timing"] = market_timing_result

    # 4. 保存报告
    report_path = save_report(report)
    logger.info(f"报告已保存: {report_path}")

    # 同时保存一份 latest.json 供前端读取
    latest_path = os.path.join(Config.DATA_DIR, "latest.json")
    from backend.utils.helpers import save_json
    save_json(report["json"], latest_path)
    logger.info(f"最新报告已保存: {latest_path}")

    # 5. 推送飞书
    if enable_push and Config.FEISHU_WEBHOOK_URL:
        logger.info("--- 步骤4: 推送飞书 ---")
        push_daily_report(report["json"])
    else:
        logger.info("跳过飞书推送（未配置 Webhook 或禁用推送）")

    logger.info("===== 分析完成 =====")
    return report


def run_screener_only():
    """仅运行选股"""
    Config.ensure_dirs()
    logger.info("===== 仅运行选股 =====")
    result = screener.run_all()

    # 保存选股结果
    from backend.utils.helpers import save_json
    path = os.path.join(Config.DATA_DIR, f"screener_{today_str()}.json")
    save_json(result, path)
    logger.info(f"选股结果已保存: {path}")

    # 打印摘要
    combined = result.get("combined", [])
    print(f"\n选股完成，共 {len(combined)} 只（多策略共振优先）")
    for c in combined[:15]:
        resonance_tag = "🔥" if c.get("resonance") else "  "
        print(f"  {resonance_tag} {c['name']}({c['code']}) {c['price']}元 "
              f"{c['pct_change']:+.1f}% | 命中{c['strategy_count']}策略 | 均分{c['avg_score']}")

    return result


def run_late_day_screener(enable_push: bool = True):
    """尾盘选股（14:30运行，推荐当日买入次日卖出的股票）"""
    Config.ensure_dirs()
    Config.ENABLE_LLM = False  # 尾盘选股禁用LLM，速度优先
    logger.info("===== 尾盘选股（14:30）=====")

    # 市场择时
    try:
        market_timing_result = market_timing_instance.analyze()
        logger.info(f"市场情绪: {market_timing_result.get('sentiment')}({market_timing_result.get('sentiment_score')}分)")
    except Exception as e:
        logger.error(f"市场择时失败: {e}")
        market_timing_result = None

    # 尾盘选股
    try:
        result = late_day_screener.screen()
    except Exception as e:
        logger.error(f"尾盘选股失败: {e}")
        result = {"picks": [], "error": str(e)}

    picks = result.get("picks", [])
    logger.info(f"尾盘选股完成，共推荐 {len(picks)} 只")

    # 保存结果
    from backend.utils.helpers import save_json
    path = os.path.join(Config.DATA_DIR, f"late_day_{today_str()}.json")
    save_result = {
        "date": today_str(),
        "time": "14:30",
        "market_timing": market_timing_result,
        "picks": picks,
        "summary": result.get("summary", {}),
    }
    save_json(save_result, path)
    logger.info(f"尾盘选股结果已保存: {path}")

    # 推送飞书
    if enable_push and Config.FEISHU_WEBHOOK_URL and picks:
        logger.info("--- 推送飞书尾盘选股 ---")
        push_late_day_picks(save_result)
    else:
        logger.info("跳过飞书推送（未配置 Webhook 或无推荐股票）")

    # 控制台输出
    print("\n" + "="*60)
    print(f"🎯 尾盘选股推荐 - {today_str()} 14:30")
    if market_timing_result:
        print(f"🌐 市场情绪: {market_timing_result.get('sentiment')}({market_timing_result.get('sentiment_score')}分) | 建议仓位: {market_timing_result.get('position')}")
    print("="*60)
    for i, p in enumerate(picks):
        print(f"\n{i+1}. 🎯 {p['name']}({p['code']}) {p['price']}元 {p['pct_change']:+.1f}% | 评分{p['score']}")
        print(f"   买入: {p['buy_price']}元 ({p.get('buy_price_note','')})")
        print(f"   卖出: {p['sell_price']}元 ({p.get('sell_price_note','')})")
        print(f"   止损: {p['stop_loss']}元 | 目标: {p['target_price']}元 | 盈亏比: {p.get('risk_reward_ratio','-')}")
        if p.get('analysis', {}).get('reasons'):
            print(f"   理由: {'、'.join(p['analysis']['reasons'][:3])}")
        if p.get('analysis', {}).get('risks'):
            print(f"   风险: {'、'.join(p['analysis']['risks'][:2])}")
    print("\n" + "="*60)
    logger.info("===== 尾盘选股完成 =====")
    return save_result


def run_analyze_only(codes: list):
    """仅分析指定股票"""
    Config.ensure_dirs()
    logger.info(f"===== 分析指定股票: {codes} =====")
    results = analyze_batch(codes)

    for r in results:
        if "error" in r:
            print(f"\n❌ {r.get('code', '')} 分析失败: {r['error']}")
            continue
        print(f"\n{'='*50}")
        print(f"📊 {r['name']}({r['code']}) 现价:{r['price']} {r['pct_change']:+.2f}%")
        print(f"   综合评分: {r['total_score']}/100 | 评级: {r['rating']} | 操作: {r['action']}")
        print(f"   五维: 技术{r['scores']['technical']} 基本面{r['scores']['fundamental']} "
              f"资金{r['scores']['capital']} 概念{r['scores']['concept']}")
        if r.get("risks"):
            print(f"   ⚠️ 风险: {', '.join(r['risks'])}")
        if r.get("llm_analysis") and r["llm_analysis"].get("raw"):
            print(f"   🤖 AI分析: {r['llm_analysis']['raw'][:200]}...")

    return results


def main():
    parser = argparse.ArgumentParser(description="股票分析系统")
    parser.add_argument("--analyze", type=str, help="分析指定股票，逗号分隔")
    parser.add_argument("--screener", action="store_true", help="仅运行选股")
    parser.add_argument("--quick", action="store_true", help="快速盘中分析（只分析自选股，不选股，重点买卖信号）")
    parser.add_argument("--late-day", action="store_true", help="尾盘选股（14:30运行，推荐当日买入次日卖出）")
    parser.add_argument("--no-push", action="store_true", help="禁用飞书推送")
    parser.add_argument("--no-llm", action="store_true", help="禁用 LLM 分析")
    parser.add_argument("--dry-run", action="store_true", help="试运行（不保存不推送）")
    parser.add_argument("--force", action="store_true", help="非交易日也强制运行")
    args = parser.parse_args()

    # 交易日判断
    if not args.force and not is_trading_day():
        logger.info("今天不是交易日，跳过分析。如需强制运行请加 --force")
        return

    if args.analyze:
        codes = [c.strip() for c in args.analyze.split(",") if c.strip()]
        run_analyze_only(codes)
    elif args.screener:
        run_screener_only()
    elif args.quick:
        push = not args.no_push and not args.dry_run
        run_quick_analysis(enable_push=push)
    elif args.late_day:
        push = not args.no_push and not args.dry_run
        run_late_day_screener(enable_push=push)
    else:
        push = not args.no_push and not args.dry_run
        llm = not args.no_llm
        run_full_analysis(enable_push=push, enable_llm=llm)


if __name__ == "__main__":
    main()
