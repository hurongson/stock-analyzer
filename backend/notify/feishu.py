"""
飞书推送模块
支持 Webhook 机器人推送，支持签名校验
"""
import json
import time
import hmac
import hashlib
import base64
import logging
import requests
from typing import Dict
from backend.config import Config

logger = logging.getLogger(__name__)


def gen_sign(secret: str, timestamp: int) -> str:
    """生成飞书签名"""
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256
    ).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def send_feishu_text(content: str, webhook_url: str = None) -> bool:
    """发送纯文本消息"""
    url = webhook_url or Config.FEISHU_WEBHOOK_URL
    if not url:
        logger.warning("飞书 Webhook 未配置，跳过推送")
        return False

    payload = {
        "msg_type": "text",
        "content": {"text": content}
    }

    if Config.FEISHU_SECRET:
        timestamp = int(time.time())
        payload["timestamp"] = str(timestamp)
        payload["sign"] = gen_sign(Config.FEISHU_SECRET, timestamp)

    try:
        resp = requests.post(url, json=payload, timeout=10)
        result = resp.json()
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            logger.info("飞书文本消息发送成功")
            return True
        else:
            logger.error(f"飞书发送失败: {result}")
            return False
    except Exception as e:
        logger.error(f"飞书发送异常: {e}")
        return False



def _format_three_locks(stock_data: Dict) -> str:
    """格式化三把锁状态字符串"""
    tl = stock_data.get("three_locks")
    if not tl:
        return ""
    total = tl.get("total_locked", 0)
    signal = tl.get("signal", "")
    t = tl.get("trend_lock", {})
    a = tl.get("activity_lock", {})
    c = tl.get("capital_lock", {})
    t_icon = "🔒" if t.get("locked") else "🔓"
    a_icon = "🔒" if a.get("locked") else "🔓"
    c_icon = "🔒" if c.get("locked") else "🔓"
    return f" | 三锁{t_icon}{a_icon}{c_icon}({total}/3){signal}"


def send_feishu_card(report_data: Dict, webhook_url: str = None) -> bool:
    """
    发送飞书卡片消息（分析日报摘要）
    """
    url = webhook_url or Config.FEISHU_WEBHOOK_URL
    if not url:
        logger.warning("飞书 Webhook 未配置，跳过推送")
        return False

    date = report_data.get("date", "")
    analyses = report_data.get("stock_analyses", [])
    screener = report_data.get("screener_result", {})
    market_timing = report_data.get("market_timing", {})
    hold_stocks = report_data.get("hold_stocks", [])  # 我的持有股票
    reverse_screen = report_data.get("reverse_screen", {})  # 反向筛选（空头模式）

    # 构建卡片内容
    elements = []

    # 标题
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"**📈 股票分析日报 - {date}**"
        }
    })

    # 市场择时
    if market_timing and market_timing.get("sentiment"):
        sentiment = market_timing.get("sentiment", "")
        sentiment_score = market_timing.get("sentiment_score", 50)
        position = market_timing.get("position", "50%")
        reasons = market_timing.get("reasons", [])
        sentiment_emoji = "🟢" if sentiment_score >= 60 else ("🔴" if sentiment_score <= 40 else "🟡")
        reasons_str = "、".join(reasons[:3]) if reasons else ""
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**🌐 市场择时** {sentiment_emoji}{sentiment}({sentiment_score}分) | 建议仓位:{position}\n"
                           f"   {reasons_str}"
            }
        })
        elements.append({"tag": "hr"})

    # 选股摘要（显示推荐股票数量，确保用户知道有推荐）
    if screener:
        combined_count = len(screener.get("combined", []))
        special_count = len(screener.get("special_picks", []))
        chen_xiaoqun_count = len(screener.get("chen_xiaoqun_picks", []))
        limit_up_count = len(screener.get("limit_up_picks", []))
        if combined_count > 0 or special_count > 0 or chen_xiaoqun_count > 0 or limit_up_count > 0:
            gate = screener.get("market_gate") or {}
            blocked = bool(gate.get("enabled") and gate.get("blocked"))
            if blocked:
                # 退潮/高潮：顶部状态条，明确无买入推荐，综合池仅观察
                elements.append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**⛔ 情绪【{gate.get('risk_regime', '')}】 · 陈小群纪律：空仓等待，今日无买入推荐**\n"
                            f"   综合观察池{combined_count}只仅供研究，不构成买入建议；空头反向筛选照常"
                        )
                    }
                })
                elements.append({"tag": "hr"})
            else:
                summary_parts = []
                if special_count > 0:
                    summary_parts.append(f"⭐特别推荐{special_count}只")
                if chen_xiaoqun_count > 0:
                    summary_parts.append(f"🔥陈小群{chen_xiaoqun_count}只")
                if limit_up_count > 0:
                    summary_parts.append(f"⚡涨停预测{limit_up_count}只")
                if combined_count > 0:
                    summary_parts.append(f"🏆综合选股{combined_count}只")
                summary_str = " | ".join(summary_parts)
                elements.append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**🎯 今日选股推荐** {summary_str}\n"
                                   f"   👇 向下滚动查看详细推荐"
                    }
                })
                elements.append({"tag": "hr"})

    # 各类推荐股票（各策略TOP3）- 低价/技术形态/资金流/基本面/概念热点
    if screener and screener.get("strategies"):
        strategies = screener["strategies"]
        strategy_names = {
            "low_price": ("💰 低价潜力股", "低价+小市值+基本面尚可"),
            "technical_pattern": ("📊 技术形态股", "均线多头/放量突破/MACD金叉"),
            "capital_flow": ("💹 资金流入股", "主力资金持续流入+量价配合"),
            "fundamental": ("📈 基本面优质股", "低估值+高ROE+业绩增长"),
            "concept_hotspot": ("🔥 概念热点股", "近期热点题材+政策催化"),
        }
        strategy_lines = []
        for key, (name, desc) in strategy_names.items():
            stocks = strategies.get(key, [])
            if stocks:
                top3 = stocks[:3]
                stocks_str = "、".join([f"{s['name']}({s['code']})" for s in top3])
                strategy_lines.append(f"**{name}**（{len(stocks)}只）: {stocks_str}")
        if strategy_lines:
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**📋 各类推荐股票（各策略TOP3）**\n" + "\n".join(strategy_lines)
                }
            })
            elements.append({"tag": "hr"})

    # 自选股摘要 + 交易信号
    valid_analyses = [a for a in analyses if "error" not in a]
    if valid_analyses:
        summary_lines = []
        buy_list = []
        sell_list = []
        for a in valid_analyses:
            emoji = "🟢" if a.get("total_score", 50) >= 60 else ("🔴" if a.get("total_score", 50) < 40 else "🟡")
            # 交易信号
            ts = a.get("trading_signal", {})
            signal = ts.get("action", a.get("action", ""))
            signal_emoji = "🟩" if "买" in signal else ("🟥" if "卖" in signal else "⬜")
            conf = ts.get("confidence", 0)
            # 三把锁状态
            tl = a.get("three_locks", {})
            if tl:
                t_locked = "🔒" if tl.get("trend_lock", {}).get("locked") else "🔓"
                a_locked = "🔒" if tl.get("activity_lock", {}).get("locked") else "🔓"
                c_locked = "🔒" if tl.get("capital_lock", {}).get("locked") else "🔓"
                locks_str = f"{t_locked}{a_locked}{c_locked}"
                tl_signal = tl.get("signal", "")
            else:
                locks_str = ""
                tl_signal = ""

            summary_lines.append(
                f"{emoji} **{a.get('name','')}**({a.get('code','')}) "
                f"{a.get('price',0)}元 {a.get('pct_change',0):+.1f}% | "
                f"评分{a.get('total_score',0)} | {signal_emoji}{signal}"
                + (f" | 三锁{locks_str} {tl_signal}" if locks_str else "")
            )
            # 收集买卖信号
            if ts.get("signal") in ("buy", "hold_buy") and conf >= 30:
                buy_list.append(a)
            elif ts.get("signal") in ("sell", "hold_sell") and conf >= 30:
                sell_list.append(a)

        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "\n".join(summary_lines)
            }
        })

        # 买卖信号汇总（含具体点位）
        if buy_list or sell_list:
            elements.append({"tag": "hr"})
            if buy_list:
                buy_lines = []
                for a in buy_list:
                    ts = a.get("trading_signal", {})
                    reasons = "、".join(ts.get("buy_signals", [])[:2])
                    buy_price = ts.get("buy_price")
                    stop_loss = ts.get("stop_loss")
                    target = ts.get("target_price")
                    rr = ts.get("risk_reward_ratio")
                    price_info = []
                    if buy_price:
                        note = ts.get("buy_price_note", "")
                        price_info.append(f"买入{buy_price}元{note}")
                    if stop_loss:
                        price_info.append(f"止损{stop_loss}元")
                    if target:
                        price_info.append(f"目标{target}元")
                    if rr:
                        price_info.append(f"盈亏比{rr}")
                    price_str = " | ".join(price_info) if price_info else ""
                    # 三把锁信息
                    tl = a.get("three_locks", {})
                    tl_info = ""
                    if tl:
                        t_score = tl.get("trend_lock", {}).get("score", 0)
                        a_score = tl.get("activity_lock", {}).get("score", 0)
                        c_score = tl.get("capital_lock", {}).get("score", 0)
                        total_locked = tl.get("total_locked", 0)
                        tl_info = f"\n  🔒三把锁: {total_locked}/3点亮 | 趋势{t_score}分 股性{a_score}分 资金{c_score}分"
                        if tl.get("signal"):
                            tl_info += f" | {tl['signal']}"
                    buy_lines.append(f"• **{a['name']}**({a['code']}) 现价{a['price']}元 | 置信度{ts.get('confidence',0)}%\n  {price_str}\n  理由: {reasons}{tl_info}")
                elements.append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**🟩 买入信号（{len(buy_list)}只）**\n" + "\n".join(buy_lines)
                    }
                })
            if sell_list:
                sell_lines = []
                for a in sell_list:
                    ts = a.get("trading_signal", {})
                    reasons = "、".join(ts.get("sell_signals", [])[:2])
                    sell_price = ts.get("sell_price")
                    stop_loss = ts.get("stop_loss")
                    price_info = []
                    if sell_price:
                        note = ts.get("sell_price_note", "")
                        price_info.append(f"卖出{sell_price}元{note}")
                    if stop_loss:
                        price_info.append(f"止损{stop_loss}元")
                    price_str = " | ".join(price_info) if price_info else ""
                    # 三把锁信息
                    tl = a.get("three_locks", {})
                    tl_info = ""
                    if tl:
                        total_locked = tl.get("total_locked", 0)
                        tl_info = f"\n  🔒三把锁: {total_locked}/3点亮 | {tl.get('signal', '')}"
                    sell_lines.append(f"• **{a['name']}**({a['code']}) 现价{a['price']}元 | 置信度{ts.get('confidence',0)}%\n  {price_str}\n  理由: {reasons}{tl_info}")
                elements.append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**🟥 卖出信号（{len(sell_list)}只）**\n" + "\n".join(sell_lines)
                    }
                })

    # 复合情绪闸门：退潮/高潮日无买入推荐，醒目提示（避免误以为程序出错）
    if screener and screener.get("market_gate"):
        gate = screener["market_gate"]
        if gate.get("enabled") and gate.get("blocked"):
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**⛔ 情绪【{gate.get('risk_regime', '')}】 · 陈小群纪律：空仓等待，今日无买入推荐**\n"
                        f"{gate.get('note', '')}\n"
                        f"（炸板率{gate.get('zhaban_rate', 0)}%、跌停{gate.get('dieting_count', 0)}只、"
                        f"最弱指数{gate.get('idx_weak_pct', 0)}%、最高{gate.get('max_lb', 0)}板）\n"
                        f"下方综合/策略名单仅为观察研究对象，不构成买入建议；空头反向筛选照常。"
                    )
                }
            })

    # 选股推荐 - 特别推荐（重点关注）
    if screener and screener.get("special_picks"):
        special_picks = screener["special_picks"]
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**⭐ 特别推荐（{len(special_picks)}只，重点关注）**"
            }
        })
        special_lines = []
        for i, c in enumerate(special_picks):
            ts = c.get("trading_signal") or {}
            buy_p = ts.get("buy_price")
            sell_p = ts.get("sell_price")
            stop_p = ts.get("stop_loss")
            target_p = ts.get("target_price")
            point_info = []
            if buy_p:
                point_info.append(f"买{buy_p}")
            if sell_p:
                point_info.append(f"卖{sell_p}")
            if stop_p:
                point_info.append(f"止损{stop_p}")
            if target_p:
                point_info.append(f"目标{target_p}")
            point_str = f" | {'/'.join(point_info)}" if point_info else ""
            reasons = "、".join(c.get("special_reasons", [])[:3])
            tl_str = _format_three_locks(c)
            special_lines.append(
                f"{i+1}. ⭐ **{c['name']}**({c['code']}) {c['price']}元 "
                f"{c['pct_change']:+.1f}% | 评分{c.get('avg_score',0)}{point_str}{tl_str}\n"
                f"   原因: {reasons}"
            )
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "\n".join(special_lines)
            }
        })

    # 选股推荐 - 陈小群风格特别推荐（独立列表，5只）
    # 核心标准：逻辑硬 + 板块合力（最重要）+ 量价市值 + 四类有效涨停
    if screener and screener.get("chen_xiaoqun_picks"):
        chen_picks = screener["chen_xiaoqun_picks"]
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**🔥 陈小群风格特别推荐（{len(chen_picks)}只，板块合力+量价市值+四类有效涨停）**\n"
                           f"陈小群名言：买在分歧、卖在一致、死守主线、只做真龙"
            }
        })
        chen_lines = []
        for i, c in enumerate(chen_picks):
            ts = c.get("trading_signal") or {}
            buy_p = ts.get("buy_price")
            sell_p = ts.get("sell_price")
            stop_p = ts.get("stop_loss")
            target_p = ts.get("target_price")
            point_info = []
            if buy_p:
                point_info.append(f"买{buy_p}")
            if sell_p:
                point_info.append(f"卖{sell_p}")
            if stop_p:
                point_info.append(f"止损{stop_p}")
            if target_p:
                point_info.append(f"目标{target_p}")
            point_str = f" | {'/'.join(point_info)}" if point_info else ""
            reasons = "、".join(c.get("chen_xiaoqun_reasons", [])[:3])
            chen_score = c.get("chen_xiaoqun_score", 0)
            tl_str = _format_three_locks(c)
            chen_lines.append(
                f"{i+1}. 🔥 **{c['name']}**({c['code']}) {c['price']}元 "
                f"{c['pct_change']:+.1f}% | 陈小群评分{chen_score}{point_str}{tl_str}\n"
                f"   理由: {reasons}"
            )
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "\n".join(chen_lines)
            }
        })

    # 选股推荐 - 涨停预测
    if screener and screener.get("limit_up_picks"):
        limit_up_picks = screener["limit_up_picks"]
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**🔥 涨停预测（{len(limit_up_picks)}只，未来1-3天关注）**"
            }
        })
        limit_up_lines = []
        for i, c in enumerate(limit_up_picks):
            ts = c.get("trading_signal") or {}
            prob = c.get("limit_up_probability", 0)
            buy_p = ts.get("buy_price")
            sell_p = ts.get("sell_price")
            stop_p = ts.get("stop_loss")
            point_info = []
            if buy_p:
                point_info.append(f"买{buy_p}")
            if sell_p:
                point_info.append(f"卖{sell_p}")
            if stop_p:
                point_info.append(f"止损{stop_p}")
            point_str = f" | {'/'.join(point_info)}" if point_info else ""
            reasons = "、".join(c.get("limit_up_reasons", [])[:3])
            tl_str = _format_three_locks(c)
            limit_up_lines.append(
                f"{i+1}. 🔥 **{c['name']}**({c['code']}) {c['price']}元 "
                f"{c['pct_change']:+.1f}% | 涨停概率{prob:.0f}%{point_str}{tl_str}\n"
                f"   理由: {reasons}"
            )
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "\n".join(limit_up_lines)
            }
        })

    # 选股推荐 - 综合TOP 10
    if screener and screener.get("combined"):
        combined = screener["combined"]
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**🏆 综合选股 TOP 10（共{len(combined)}只）**"
            }
        })
        top_lines = []
        for i, c in enumerate(combined[:10]):
            resonance_tag = "🔥" if c.get("resonance") else "  "
            ts = c.get("trading_signal") or {}
            buy_p = ts.get("buy_price")
            sell_p = ts.get("sell_price")
            stop_p = ts.get("stop_loss")
            point_info = []
            if buy_p:
                point_info.append(f"买{buy_p}")
            if sell_p:
                point_info.append(f"卖{sell_p}")
            if stop_p:
                point_info.append(f"止损{stop_p}")
            point_str = f" | {'/'.join(point_info)}" if point_info else ""
            tl_str = _format_three_locks(c)
            top_lines.append(
                f"{i+1}. {resonance_tag} **{c['name']}**({c['code']}) {c['price']}元 "
                f"{c['pct_change']:+.1f}%{point_str}{tl_str}"
            )
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "\n".join(top_lines)
            }
        })

        # 多策略共振选股（重点关注）
        resonance = [c for c in combined if c.get("resonance")]
        if resonance:
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**🎯 多策略共振选股（{len(resonance)}只，重点关注）**"
                }
            })
            pick_lines = []
            for c in resonance[:8]:
                ts = c.get("trading_signal") or {}
                buy_p = ts.get("buy_price")
                sell_p = ts.get("sell_price")
                point_info = []
                if buy_p:
                    point_info.append(f"买{buy_p}")
                if sell_p:
                    point_info.append(f"卖{sell_p}")
                point_str = f" | {'/'.join(point_info)}" if point_info else ""
                tl_str = _format_three_locks(c)
                pick_lines.append(
                    f"• **{c['name']}**({c['code']}) {c['price']}元 "
                    f"{c['pct_change']:+.1f}% | 命中{c['strategy_count']}策略{point_str}{tl_str}"
                )
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "\n".join(pick_lines)
                }
            })

    # 各策略精选（每个策略前10名）
    if screener and screener.get("strategies"):
        strategy_names = {
            "low_price": "低价潜力",
            "technical_pattern": "技术形态",
            "capital_flow": "资金流入",
            "fundamental": "基本面优",
            "concept_hotspot": "概念热点",
        }
        # 建立 code -> trading_signal 映射（从综合选股结果中）
        signal_map = {}
        if screener.get("combined"):
            for c in screener["combined"]:
                if c.get("trading_signal"):
                    signal_map[c["code"]] = c["trading_signal"]

        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**📊 各策略精选（前10名）**"
            }
        })
        for sname, sresults in screener["strategies"].items():
            if sresults:
                strategy_lines = []
                for i, top in enumerate(sresults[:10]):
                    ts = signal_map.get(top["code"]) or {}
                    buy_p = ts.get("buy_price")
                    sell_p = ts.get("sell_price")
                    point_info = []
                    if buy_p:
                        point_info.append(f"买{buy_p}")
                    if sell_p:
                        point_info.append(f"卖{sell_p}")
                    point_str = f" | {'/'.join(point_info)}" if point_info else ""
                    # 从combined中查找三把锁数据
                    tl_data = None
                    for comb in screener.get("combined", []):
                        if comb.get("code") == top["code"]:
                            tl_data = comb
                            break
                    tl_str = _format_three_locks(tl_data) if tl_data else ""
                    strategy_lines.append(
                        f"  {i+1}. {top['name']}({top['code']}) {top['price']}元 "
                        f"{top['pct_change']:+.1f}%{point_str}{tl_str}"
                    )
                elements.append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**{strategy_names.get(sname, sname)}**（{len(sresults)}只）\n" + "\n".join(strategy_lines)
                    }
                })

    # 我的关注股票（自选股详细分析）
    if valid_analyses:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**👁️ 我的关注股票（{len(valid_analyses)}只）**"
            }
        })
        watch_lines = []
        for a in valid_analyses:
            ts = a.get("trading_signal", {})
            signal = ts.get("action", a.get("action", "持有观望"))
            conf = ts.get("confidence", 0)
            buy_p = ts.get("buy_price")
            sell_p = ts.get("sell_price")
            stop_p = ts.get("stop_loss")
            target_p = ts.get("target_price")
            rr = ts.get("risk_reward_ratio")
            point_info = []
            if buy_p:
                note = ts.get("buy_price_note", "")
                point_info.append(f"买{buy_p}{note}")
            if sell_p:
                note = ts.get("sell_price_note", "")
                point_info.append(f"卖{sell_p}{note}")
            if stop_p:
                point_info.append(f"止损{stop_p}")
            if target_p:
                point_info.append(f"目标{target_p}")
            if rr:
                point_info.append(f"盈亏比{rr}")
            point_str = f" | {'/'.join(point_info)}" if point_info else ""
            watch_lines.append(
                f"• **{a.get('name','')}**({a.get('code','')}) {a.get('price',0)}元 "
                f"{a.get('pct_change',0):+.1f}% | 评分{a.get('total_score',0)} | "
                f"{signal}({conf}%){point_str}"
            )
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "\n".join(watch_lines)
            }
        })

    # 我的持有股票（独立模块，重点关注买卖信号）
    valid_hold = [a for a in hold_stocks if "error" not in a]
    if valid_hold:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**💼 我的持有股票（{len(valid_hold)}只，重点关注买卖信号）**"
            }
        })
        hold_lines = []
        for a in valid_hold:
            ts = a.get("trading_signal", {})
            signal = ts.get("action", a.get("action", "持有观望"))
            conf = ts.get("confidence", 0)
            buy_p = ts.get("buy_price")
            sell_p = ts.get("sell_price")
            stop_p = ts.get("stop_loss")
            target_p = ts.get("target_price")
            point_info = []
            if buy_p:
                point_info.append(f"买{buy_p}")
            if sell_p:
                point_info.append(f"卖{sell_p}")
            if stop_p:
                point_info.append(f"止损{stop_p}")
            if target_p:
                point_info.append(f"目标{target_p}")
            point_str = f" | {'/'.join(point_info)}" if point_info else ""
            tl_str = _format_three_locks(a)
            signal_emoji = "🟩" if "买" in signal else ("🟥" if "卖" in signal else "⬜")
            hold_lines.append(
                f"• **{a.get('name','')}**({a.get('code','')}) {a.get('price',0)}元 "
                f"{a.get('pct_change',0):+.1f}% | 评分{a.get('total_score',0)} | "
                f"{signal_emoji}{signal}({conf}%){point_str}{tl_str}"
            )
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "\n".join(hold_lines)
            }
        })

    # 反向筛选（空头模式）- 帮你少犯"什么都想买"的错
    if reverse_screen and reverse_screen.get("total_candidates"):
        elements.append({"tag": "hr"})
        eliminated_count = len(reverse_screen.get("eliminated", []))
        downgraded_count = len(reverse_screen.get("downgraded", []))
        kept_count = len(reverse_screen.get("kept", []))
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**🔍 反向筛选（空头模式）- 帮你少犯'什么都想买'的错**\n"
                           f"候选{reverse_screen.get('total_candidates')}只 | 淘汰{eliminated_count}只 | "
                           f"降级{downgraded_count}只 | 保留{kept_count}只\n"
                           f"核心理念：不是帮你发现更多机会，而是帮你学会放弃绝大多数机会"
            }
        })
        # 淘汰原因统计
        elimination_reasons = reverse_screen.get("elimination_reasons", {})
        if elimination_reasons:
            reason_lines = []
            for reason, count in sorted(elimination_reasons.items(), key=lambda x: x[1], reverse=True)[:5]:
                reason_lines.append(f"  • {reason}: {count}只")
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**淘汰原因：**\n" + "\n".join(reason_lines)
                }
            })
        # 三级漏斗 + 核心池
        funnel = reverse_screen.get("three_level_funnel", {})
        if funnel:
            core = funnel.get("core_pool", [])
            core_str = "、".join(f"{s.get('name')}({s.get('code')})" for s in core)
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**三级漏斗：** 观察池{len(funnel.get('observation_pool', []))} / "
                               f"研究池{len(funnel.get('research_pool', []))} / 核心池{len(core)}\n"
                               f"**核心池：** {core_str}"
                }
            })
        # 被淘汰股票列表
        eliminated_stocks = reverse_screen.get("eliminated", [])
        if eliminated_stocks:
            elim_lines = []
            for s in eliminated_stocks[:5]:
                elim_lines.append(f"  • {s.get('name')}({s.get('code')})")
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**被淘汰股票（前5只）：**\n" + "\n".join(elim_lines)
                }
            })

    # 底部
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "elements": [{
            "tag": "plain_text",
            "content": "⚠️ 本报告由 AI 自动生成，仅供参考，不构成投资建议"
        }]
    })

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"📈 股票分析日报 {date}"
                },
                "template": "blue"
            },
            "elements": elements
        }
    }

    if Config.FEISHU_SECRET:
        timestamp = int(time.time())
        payload["timestamp"] = str(timestamp)
        payload["sign"] = gen_sign(Config.FEISHU_SECRET, timestamp)

    try:
        resp = requests.post(url, json=payload, timeout=15)
        result = resp.json()
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            logger.info("飞书卡片消息发送成功")
            return True
        else:
            logger.error(f"飞书卡片发送失败: {result}")
            return False
    except Exception as e:
        logger.error(f"飞书卡片发送异常: {e}")
        return False


def push_daily_report(report_data: Dict) -> bool:
    """推送每日报告（优先卡片，失败回退文本）"""
    success = send_feishu_card(report_data)
    if not success:
        # 回退到文本摘要
        md = report_data.get("markdown", "")
        if md:
            # 截取前2000字（飞书文本消息有长度限制）
            summary = md[:2000] + "\n\n...(内容过长，完整报告请查看前端页面)"
            success = send_feishu_text(summary)
    return success


def push_standstill_notice(market_sentiment: Dict, webhook_url: str = None) -> bool:
    """退潮空仓提示：尾盘无推荐时也推送，告知今日为何空仓（避免用户误以为程序出错）"""
    try:
        from datetime import datetime
        ms = market_sentiment or {}
        note = ms.get("note", "情绪退潮，今日尾盘空仓观望，等待冰点")
        content = (
            f"【尾盘空仓提示】{datetime.now().strftime('%Y-%m-%d')}\n"
            f"今日尾盘不做任何买入推荐，建议空仓观望。\n"
            f"判定原因：{note}\n"
            f"——陈小群：退潮期空仓等待冰点，不逆势抄底、不试错。"
        )
        return send_feishu_text(content, webhook_url)
    except Exception as e:
        logging.getLogger(__name__).warning(f"空仓提示推送失败: {e}")
        return False


def push_late_day_picks(late_day_data: Dict, webhook_url: str = None) -> bool:
    """
    推送尾盘选股结果（14:30）
    late_day_data: {date, time, market_timing, picks: [...], summary}
    """
    url = webhook_url or Config.FEISHU_WEBHOOK_URL
    if not url:
        logger.warning("飞书 Webhook 未配置，跳过推送")
        return False

    date = late_day_data.get("date", "")
    picks = late_day_data.get("picks", [])
    # 获取精选10支、全部30支和陈小群风格特别推荐5支（适配新的返回结构）
    # 严格类型检查：确保top_picks和all_picks都是列表，不是字典（修复TypeError）
    top_picks = late_day_data.get("top_picks", [])
    all_picks = late_day_data.get("all_picks", picks)
    special_picks = late_day_data.get("special_picks", [])  # 陈小群风格特别推荐5支
    
    # 如果top_picks不是列表，转换成空列表（修复字典被当成列表的问题）
    if not isinstance(top_picks, list):
        logger.warning(f"top_picks不是列表，类型: {type(top_picks)}，转换为空列表")
        top_picks = []
    
    # 如果all_picks不是列表，转换成空列表
    if not isinstance(all_picks, list):
        logger.warning(f"all_picks不是列表，类型: {type(all_picks)}，转换为空列表")
        all_picks = []
    
    # 如果picks不是列表，转换成空列表
    if not isinstance(picks, list):
        logger.warning(f"picks不是列表，类型: {type(picks)}，转换为空列表")
        picks = []
    
    # 尾盘自动核查结果（人工闭环自动化）
    auto_check = late_day_data.get("auto_check", {}) or {}
    ac_block = bool(auto_check.get("all_rejected"))  # 候选全部被核查剔除，仍需推送报警

    market_timing = late_day_data.get("market_timing", {})

    # 如果没有top_picks，从all_picks中取前10只
    if not top_picks and all_picks:
        top_picks = all_picks[:10]

    if not all_picks and not ac_block:
        logger.info("无尾盘选股推荐，跳过推送")
        return False
    if ac_block:
        logger.warning("尾盘候选经自动核查全部剔除，推送不通过报警")

    elements = []

    # 标题
    if ac_block:
        _title_md = (f"**🛑 尾盘自动核查·全部不通过 - {date} 14:30**\n"
                     f"当日 {auto_check.get('checked', 0)} 只候选经 主线/量价/位置 核查后全部剔除\n"
                     f"**今日不建议买入，空仓观望**")
    else:
        _title_md = (f"**🎯 尾盘选股推荐 - {date} 14:30**\n"
                     f"当日买入，次日冲高卖出（T+1短线）\n"
                     f"共推荐{len(all_picks)}只，精选{len(top_picks)}只，陈小群风格特别推荐{len(special_picks)}只")
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": _title_md
        }
    })

    # ===== 尾盘自动核查结果（主线共振 / 量价 / 位置·背离；异常报警）=====
    if auto_check and auto_check.get("checked", 0) > 0:
        _n = auto_check["checked"]
        _np = auto_check.get("passed", 0)
        _nw = auto_check.get("warned", 0)
        _nr = auto_check.get("rejected", 0)
        if auto_check.get("all_rejected"):
            _sumicon = "🛑"
        elif _nr > 0:
            _sumicon = "⚠️"
        elif auto_check.get("all_pass"):
            _sumicon = "✅"
        else:
            _sumicon = "🛡️"
        _sum = (f"**{_sumicon} 尾盘自动核查（主线共振·量价配合·位置/背离）**\n"
                f"   核查{_n}只：✅通过{_np}、🟡警告{_nw}、⛔剔除{_nr}")
        if auto_check.get("sector_data_skipped"):
            _sum += "\n   ⚠️ 涨停板块数据缺失，主线项未参与硬判（仅量价/位置核查）"
        if auto_check.get("all_rejected"):
            _sum += "\n   **🛑 全部候选未通过核查，今日不建议买入、空仓观望！**"
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": _sum}})

        # 剔除明细（硬伤原因）
        for it in auto_check.get("rejected_items", [])[:12]:
            _why = "、".join(it.get("hard_reasons", []))
            if not _why:
                _d = [b.get("detail", "") for b in it.get("blocks", {}).values() if b.get("status") == "fail"]
                _why = "；".join([x for x in _d if x])
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md",
                         "content": f"⛔ **{it.get('name', '')}({it.get('code', '')})** {_why}"}
            })

        # 警告汇总（保留，需人工确认）
        _wlines = []
        for it in auto_check.get("warned_items", [])[:15]:
            _m = "、".join(it.get("marks", [])) or "形态/量价需留意"
            _wlines.append(f"{it.get('name', '')}({_m})")
        if _wlines:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md",
                         "content": "🟡 **警告（保留，需人工确认）**: " + "；".join(_wlines)}
            })
        elements.append({"tag": "hr"})

    # 市场择时
    if market_timing and market_timing.get("sentiment"):
        sentiment = market_timing.get("sentiment", "")
        sentiment_score = market_timing.get("sentiment_score", 50)
        position = market_timing.get("position", "50%")
        reasons = market_timing.get("reasons", [])
        sentiment_emoji = "🟢" if sentiment_score >= 60 else ("🔴" if sentiment_score <= 40 else "🟡")
        reasons_str = "、".join(reasons[:2]) if reasons else ""
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**🌐 市场环境** {sentiment_emoji}{sentiment}({sentiment_score}分) | 建议仓位:{position}\n"
                           f"   {reasons_str}"
            }
        })
        elements.append({"tag": "hr"})

    # 2026-09-23新增：运行时段与盘前滞后警告（短板一）
    market_sentiment = late_day_data.get("market_sentiment", {})
    run_timing = market_sentiment.get("run_timing", "")
    stale_warning = market_sentiment.get("stale_warning", "")
    if run_timing:
        _timing_emoji = {"盘前": "🔴", "盘中": "🟡", "尾盘": "🟢", "盘后": "⚪"}.get(run_timing, "")
        _timing_content = f"**⏰ 运行时段** {_timing_emoji}{run_timing}"
        if stale_warning:
            _timing_content += f"\n   ⚠️ {stale_warning}"
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": _timing_content}})
        elements.append({"tag": "hr"})

    # 陈小群风格特别推荐5支（新增：结合陈小群选股方式）
    if special_picks:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**🔥 陈小群风格特别推荐（{len(special_picks)}只，板块合力+量价市值+四类有效涨停）**"
            }
        })

        for i, p in enumerate(special_picks):
            # 类型检查：确保p是字典
            if not isinstance(p, dict):
                continue
            name = p.get("name", p.get("code", ""))
            code = p.get("code", "")
            price = p.get("price", 0)
            pct = p.get("pct_change", 0)
            score = p.get("chen_xiaoqun_score", 0)
            reasons = p.get("chen_xiaoqun_reasons", [])
            reasons_str = "、".join(reasons[:2]) if reasons else ""
            
            pct_emoji = "📈" if pct >= 0 else "📉"
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"{i+1}. **{name}({code})** {price}元 {pct_emoji}{pct:+.1f}% | 陈小群评分{score:.0f}\n"
                               f"   理由: {reasons_str}"
                }
            })

    # 精选10支详细推荐
    if top_picks:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**⭐ 精选推荐（{len(top_picks)}只，重点关注）**"
            }
        })

        for i, p in enumerate(top_picks):
            # 类型检查：确保p是字典，跳过字符串等非字典元素（修复AttributeError）
            if not isinstance(p, dict):
                logger.warning(f"跳过非字典元素: {type(p)} - {p}")
                continue
            buy_price = p.get("buy_price")
            sell_price = p.get("sell_price")
            stop_loss = p.get("stop_loss")
            target_price = p.get("target_price")
            rr = p.get("risk_reward_ratio")
            score = p.get("score", 0)

            # 买卖点位
            point_info = []
            if buy_price:
                point_info.append(f"买入{buy_price}元")
            if sell_price:
                point_info.append(f"卖出{sell_price}元")
            if stop_loss:
                point_info.append(f"止损{stop_loss}元")
            if target_price:
                point_info.append(f"目标{target_price}元")
            if rr:
                point_info.append(f"盈亏比{rr}")
            point_str = " | ".join(point_info)

            # 分析理由
            reasons = p.get("analysis", {}).get("reasons", [])
            risks = p.get("analysis", {}).get("risks", [])
            reasons_str = "、".join(reasons[:3]) if reasons else ""
            risks_str = "、".join(risks[:2]) if risks else ""

            # 三把锁状态
            tl = p.get("three_locks", {})
            tl_str = ""
            if tl:
                t_locked = "🔒" if tl.get("trend_lock", {}).get("locked") else "🔓"
                a_locked = "🔒" if tl.get("activity_lock", {}).get("locked") else "🔓"
                c_locked = "🔒" if tl.get("capital_lock", {}).get("locked") else "🔓"
                total_locked = tl.get("total_locked", 0)
                tl_signal = tl.get("signal", "")
                tl_str = f"\n   🔒三把锁: {total_locked}/3 {t_locked}趋势 {a_locked}股性 {c_locked}资金 | {tl_signal}"

            # 消息面状态（结合时事新闻、政策消息、公司公告）
            news_impact = p.get("news_impact", {})
            news_str = ""
            if news_impact:
                news_level = news_impact.get("level", "中性")
                news_score = news_impact.get("score", 50)
                news_reasons = news_impact.get("reasons", [])
                news_reasons_str = "、".join(news_reasons[:2]) if news_reasons else ""
                if news_level in ["利好", "偏利好"]:
                    news_emoji = "📰"
                elif news_level in ["利空", "偏利空"]:
                    news_emoji = "⚠️"
                else:
                    news_emoji = "📄"
                news_str = f"\n   {news_emoji}消息面: {news_level}({news_score}分)"
                if news_reasons_str:
                    news_str += f" | {news_reasons_str}"

            # 涨停概率和原因（基于6个月460只涨停股回测分析）
            analysis = p.get("analysis", {})
            limit_up_prob = analysis.get("limit_up_probability", 0)
            limit_up_reasons = analysis.get("limit_up_reasons", [])
            limit_up_str = ""
            if limit_up_prob > 0:
                prob_emoji = "🔥" if limit_up_prob >= 60 else "⚡" if limit_up_prob >= 45 else "📈"
                limit_up_str = f"\n   {prob_emoji}涨停概率: {limit_up_prob}%"
                if limit_up_reasons:
                    limit_up_str += f" | {'、'.join(limit_up_reasons[:3])}"

            # 基本面变化和逻辑反证（新增，基于表1和表4逻辑）
            analysis = p.get("analysis", {})
            fundamental_score = analysis.get("fundamental_score", 0)
            fundamental_changes = analysis.get("fundamental_changes", [])
            fundamental_research = analysis.get("fundamental_research", "")
            counter_evidences = analysis.get("counter_evidences", [])
            has_counter_evidence = analysis.get("has_counter_evidence", False)
            
            fundamental_str = ""
            if fundamental_changes or fundamental_research:
                fundamental_emoji = "📊" if fundamental_score >= 5 else "📉" if fundamental_score < 0 else "📋"
                fundamental_str = f"\n   {fundamental_emoji}基本面: {fundamental_score}分"
                if fundamental_changes:
                    fundamental_str += f" | {'、'.join(fundamental_changes[:2])}"
                if fundamental_research:
                    fundamental_str += f"\n   🔍 {fundamental_research}"
            
            counter_str = ""
            if counter_evidences:
                counter_str = f"\n   ⚠️ 逻辑反证: {'；'.join(counter_evidences[:2])}"

            content = (
                f"**{i+1}. ⭐ {p['name']}({p['code']})** {p['price']}元 {p['pct_change']:+.1f}% | 评分{score}\n"
                f"   {point_str}"
                f"{tl_str}"
                f"{news_str}"
                f"{limit_up_str}"
                f"{fundamental_str}"
                f"{counter_str}\n"
                f"   ✅ 理由: {reasons_str}"
            )
            if risks_str:
                content += f"\n   ⚠️ 风险: {risks_str}"

            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": content
                }
            })

    # 全部30支简要列表
    if all_picks and len(all_picks) > len(top_picks):
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**📋 全部推荐（{len(all_picks)}只，简要列表）**"
            }
        })

        # 分批显示，每批10只
        for batch_start in range(0, len(all_picks), 10):
            batch = all_picks[batch_start:batch_start+10]
            batch_str = ""
            for j, p in enumerate(batch):
                # 类型检查：确保p是字典，跳过字符串等非字典元素（修复AttributeError）
                if not isinstance(p, dict):
                    logger.warning(f"跳过非字典元素: {type(p)} - {p}")
                    continue
                idx = batch_start + j + 1
                score = p.get("score", 0)
                limit_up_prob = p.get("analysis", {}).get("limit_up_probability", 0)
                batch_str += f"{idx}. {p['name']}({p['code']}) {p['price']}元 评分{score}"
                if limit_up_prob > 0:
                    batch_str += f" 涨停{limit_up_prob}%"
                batch_str += "\n"

            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": batch_str.strip()
                }
            })

    # 操作提示（优化：增加更详细的止损和仓位控制提醒）
    # 基于2026-09-02回测：大盘下跌时推荐股票平均亏损3.35%，需要严格止损
    market_timing = late_day_data.get("market_timing", {})
    market_sentiment = market_timing.get("sentiment", "")
    market_score = market_timing.get("sentiment_score", 50)
    
    # 大盘环境风险提示
    risk_warning = ""
    if market_score < 40 or "跌" in market_sentiment:
        risk_warning = "\n⚠️ **大盘环境偏弱，建议降低仓位，严格止损！**"
    
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"**📌 操作提示与风险控制**{risk_warning}\n"
                       "• 买入时机：今日14:30-15:00尾盘买入，不追高\n"
                       "• 卖出时机：次日冲高3%-5%分批卖出，不贪心\n"
                       "• 止损纪律：跌破止损价立即止损，亏损达2%无条件止损\n"
                       "• 仓位控制：单只股票不超过总仓位10%，总仓位不超过50%\n"
                       "• 大盘下跌时：减少买入数量，提高选股门槛，空仓也是一种策略\n"
                       "• 特别提醒：尾盘选股为T+1短线策略，次日必须卖出，不做长线"
        }
    })

    # 反向筛选（空头模式）淘汰股展示
    # 基于博主"WorkBuddy股票淘汰器"逻辑：不是寻找值得买的股票，而是想办法淘汰股票
    reverse_screen = late_day_data.get("reverse_screen", {})
    if reverse_screen and reverse_screen.get("enabled"):
        elements.append({"tag": "hr"})
        eliminated_count = reverse_screen.get("eliminated_count", 0)
        downgraded_count = reverse_screen.get("downgraded_count", 0)
        summary = reverse_screen.get("summary", "")
        funnel = reverse_screen.get("three_level_funnel", {})

        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**🔍 反向筛选（空头模式）- 帮你少犯'什么都想买'的错**\n"
                           f"淘汰{eliminated_count}只，降级{downgraded_count}只，保留{len(all_picks)}只\n"
                           f"三级漏斗: 观察池{funnel.get('observation_pool_count', 0)}只 → 研究池{funnel.get('research_pool_count', 0)}只 → 核心池{funnel.get('core_pool_count', 0)}只"
            }
        })

        # 淘汰原因统计
        elimination_reasons = reverse_screen.get("elimination_reasons_stats", {})
        if elimination_reasons:
            top_reasons = sorted(elimination_reasons.items(), key=lambda x: -x[1])[:5]
            reasons_str = "、".join([f"{r}({c}只)" for r, c in top_reasons])
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**主要淘汰原因**: {reasons_str}"
                }
            })

        # 被淘汰的股票列表（前10只）
        eliminated_stocks = reverse_screen.get("eliminated_stocks", [])
        if eliminated_stocks:
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**❌ 被淘汰股票（前{min(10, len(eliminated_stocks))}只，为什么不值得研究）**"
                }
            })

            for i, s in enumerate(eliminated_stocks[:10]):
                name = s.get("name", "")
                code = s.get("code", "")
                score = s.get("elimination_score", 0)
                reasons = s.get("elimination_reasons", [])
                vetoed = s.get("vetoed", False)
                veto_reasons = s.get("veto_reasons", [])

                reasons_str = "、".join(reasons[:2]) if reasons else ""
                veto_str = " ⛔风险否决" if vetoed else ""
                if veto_reasons:
                    reasons_str = "、".join(veto_reasons[:1]) + ("、" + reasons_str if reasons_str else "")

                elements.append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"{i+1}. **{name}**({code}) 淘汰分{score}{veto_str}\n"
                                   f"   原因: {reasons_str}"
                    }
                })

        # 反向筛选核心理念
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "💡 **反向筛选核心理念**: AI最适合散户的用法不是帮你发现更多机会，而是帮你少犯'什么都想买'的错。股票被淘汰仅代表研究优先级降低，不代表未来价格表现。"
            }
        })

    # 底部
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "elements": [{
            "tag": "plain_text",
            "content": "⚠️ 尾盘选股为短线策略，仅供参考，不构成投资建议。股市有风险，投资需谨慎。"
        }]
    })

    if ac_block:
        _htpl, _htitle = "red", f"🛑 尾盘核查全部不通过 {date} 14:30"
    elif auto_check.get("rejected", 0) > 0:
        _htpl, _htitle = "orange", f"⚠️ 尾盘选股推荐（{auto_check.get('rejected', 0)}只未过） {date} 14:30"
    elif auto_check.get("all_pass"):
        _htpl, _htitle = "green", f"✅ 尾盘选股推荐（核查通过） {date} 14:30"
    else:
        _htpl, _htitle = "orange", f"🎯 尾盘选股推荐 {date} 14:30"

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": _htitle
                },
                "template": _htpl
            },
            "elements": elements
        }
    }

    if Config.FEISHU_SECRET:
        timestamp = int(time.time())
        payload["timestamp"] = str(timestamp)
        payload["sign"] = gen_sign(Config.FEISHU_SECRET, timestamp)

    try:
        resp = requests.post(url, json=payload, timeout=15)
        result = resp.json()
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            logger.info(f"尾盘选股飞书推送成功，共{len(picks)}只")
            return True
        else:
            logger.error(f"尾盘选股飞书推送失败: {result}")
            return False
    except Exception as e:
        logger.error(f"尾盘选股飞书推送异常: {e}")
        return False


def push_auction_picks(auction_data: Dict, webhook_url: str = None) -> bool:
    """
    推送竞价擒牛结果（交易日 9:25 集合竞价结束后）。

    auction_data: AuctionScreener.screen() 的返回
      {date, mode, snapshot_time, in_auction_window, prev_regime,
       candidate_count, top_picks: [...], groups}
    实时模式：含量能，按竞价开盘价附近介入。
    回测模式（非竞价窗口）：明确标注非实时，仅供学习，不做买入推荐。
    """
    url = webhook_url or Config.FEISHU_WEBHOOK_URL
    if not url:
        logger.warning("飞书 Webhook 未配置，跳过推送")
        return False
    if auction_data.get("error"):
        logger.warning(f"竞价擒牛出错，不推送：{auction_data['error']}")
        return False

    date = auction_data.get("date", "")
    live = bool(auction_data.get("in_auction_window"))
    mode = auction_data.get("mode", "实时竞价" if live else "回测模式")
    prev_regime = auction_data.get("prev_regime", "未知")
    top_picks = auction_data.get("top_picks", []) or []
    if not isinstance(top_picks, list):
        top_picks = []

    elements = []

    # 标题区
    if live:
        head = (f"**🐂 竞价擒牛（实时） - {date} 9:25**\n"
                f"集合竞价结束，按竞价开盘价附近介入，不追高\n"
                f"候选 {auction_data.get('candidate_count', 0)} 只，"
                f"上榜 {len(top_picks)} 只 | 昨日情绪：{prev_regime}")
    else:
        head = (f"**📗 竞价擒牛（回测模式） - {date}**\n"
                f"快照时间 {auction_data.get('snapshot_time', '')}，"
                f"**非竞价窗口、非实时，量能因子未参与，仅供学习**\n"
                f"候选 {auction_data.get('candidate_count', 0)} 只，"
                f"上榜 {len(top_picks)} 只 | 昨日情绪：{prev_regime}")
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": head}})

    if not top_picks:
        empty = (f"**今日综合擒牛榜无标的**\n"
                 f"原因：竞价高开/价格/量能不达标，或昨日 {prev_regime} 已收紧。"
                 f"空仓观望，等待弱转强。" if live else
                 f"**回测模式下无符合日线策略的标的**，可对照涨停池复盘。")
        elements.append({"tag": "hr"})
        elements.append({"tag": "div",
                         "text": {"tag": "lark_md", "content": empty}})
    else:
        elements.append({"tag": "hr"})
        for i, p in enumerate(top_picks):
            if not isinstance(p, dict):
                continue
            points = (f"买入{p.get('buy_price')}元 | 止盈{p.get('sell_price')}元"
                      f" | 目标{p.get('target_price')}元"
                      f" | 止损{p.get('stop_loss')}元"
                      f" | 盈亏比{p.get('risk_reward_ratio')}")
            vr = p.get("auction_vol_ratio")
            vr_str = f"竞价量占昨日 {vr}%" if vr is not None else "量能未验证"
            strats = "、".join(p.get("strategies", []))
            reasons = p.get("analysis", {}).get("reasons", [])
            risks = p.get("analysis", {}).get("risks", [])
            content = (f"{i+1}. **{p.get('name','')}({p.get('code','')})** "
                       f"高开 {p.get('open_pct')}% | {vr_str} | "
                       f"评分 {p.get('score')}\n"
                       f"   {points}\n"
                       f"   策略：{strats}\n"
                       f"   理由：{'、'.join(reasons[:3])}\n"
                       f"   风险：{'、'.join(risks[:2])}")
            elements.append({"tag": "div",
                             "text": {"tag": "lark_md", "content": content}})

    # 底部
    elements.append({"tag": "hr"})
    elements.append({"tag": "note", "elements": [{
        "tag": "plain_text",
        "content": "⚠️ 竞价擒牛为短线研究工具，仅供参考，不构成投资建议。股市有风险，投资需谨慎。"
    }]})

    if live:
        htpl, htitle = "green", f"🐂 竞价擒牛（实时）{date} 上榜{len(top_picks)}只"
    else:
        htpl, htitle = "blue", f"📗 竞价擒牛（回测）{date}"
    if live and not top_picks:
        htpl = "grey"

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": htitle},
                "template": htpl,
            },
            "elements": elements,
        },
    }
    if Config.FEISHU_SECRET:
        timestamp = int(time.time())
        payload["timestamp"] = str(timestamp)
        payload["sign"] = gen_sign(Config.FEISHU_SECRET, timestamp)

    try:
        resp = requests.post(url, json=payload, timeout=15)
        rj = resp.json()
        if rj.get("code") == 0 or rj.get("StatusCode") == 0:
            logger.info(f"竞价擒牛飞书推送成功，上榜{len(top_picks)}只")
            return True
        logger.error(f"竞价擒牛飞书推送失败: {rj}")
        return False
    except Exception as e:
        logger.error(f"竞价擒牛飞书推送异常: {e}")
        return False


def push_holdings_feedback(auction_data: Dict, webhook_url: str = None) -> bool:
    """
    推送持仓隔夜反馈（竞价擒牛核对前一日尾盘买入/推荐名单的次日竞价表现）。
    无持仓时不推送。
    """
    url = webhook_url or Config.FEISHU_WEBHOOK_URL
    if not url:
        logger.warning("飞书 Webhook 未配置，跳过推送")
        return False
    fb = auction_data.get("holdings_feedback") or {}
    items = fb.get("items") or []
    if not items:
        return False
    date = auction_data.get("date", "")

    color_map = {
        "强势高开": "green",
        "小幅高开": "blue",
        "小幅低开": "orange",
        "明显低开": "red",
        "触及止损": "red",
    }
    elements = []
    n_risk = sum(1 for i in items if i["status"] in ("明显低开", "触及止损"))
    n_strong = sum(1 for i in items if i["status"] == "强势高开")
    head = (f"**📋 持仓隔夜反馈 - {date} 9:25**\n"
            f"共 {len(items)} 只 | 强势 {n_strong} 只，"
            f"需警惕 {n_risk} 只\n"
            f"按竞价高开/低开与弱转强情况决定去留，严格执行止损")
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": head}})
    elements.append({"tag": "hr"})
    for i, it in enumerate(items):
        vr = f"量比{it['vol_ratio']}%" if it.get("vol_ratio") is not None else "量比未验证"
        content = (f"{i+1}. **{it['name']}({it['code']})** "
                   f"高开 {it['open_pct']}% | {vr} | "
                   f"**{it['status']}**\n"
                   f"   现价 {it['price']} | 止损 {it.get('stop_loss')} | "
                   f"目标 {it.get('target')}\n"
                   f"   建议：{it['action']}")
        elements.append({"tag": "div",
                         "text": {"tag": "lark_md", "content": content}})
    elements.append({"tag": "hr"})
    elements.append({"tag": "note", "elements": [{
        "tag": "plain_text",
        "content": "⚠️ 持仓反馈为隔夜核对参考，不构成投资建议，请结合自身持仓与风险承受能力决策。"
    }]})

    tpl = "red" if n_risk else ("green" if n_strong == len(items) else "blue")
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text",
                          "content": f"📋 持仓隔夜反馈 {date}（{len(items)}只）"},
                "template": tpl,
            },
            "elements": elements,
        },
    }
    if Config.FEISHU_SECRET:
        timestamp = int(time.time())
        payload["timestamp"] = str(timestamp)
        payload["sign"] = gen_sign(Config.FEISHU_SECRET, timestamp)

    try:
        resp = requests.post(url, json=payload, timeout=15)
        rj = resp.json()
        if rj.get("code") == 0 or rj.get("StatusCode") == 0:
            logger.info(f"持仓隔夜反馈飞书推送成功，{len(items)}只")
            return True
        logger.error(f"持仓隔夜反馈飞书推送失败: {rj}")
        return False
    except Exception as e:
        logger.error(f"持仓隔夜反馈飞书推送异常: {e}")
        return False


def push_intraday_anomaly(anomaly_data: Dict, webhook_url: str = None) -> bool:
    """
    推送盘中异动提醒（表2）
    默认保持静默，只有出现异动时才推送    anomaly_data: {has_anomaly, anomaly_count, anomalies: [...], summary, check_time}
    """
    url = webhook_url or Config.FEISHU_WEBHOOK_URL
    if not url:
        logger.warning("飞书 Webhook 未配置，跳过推送")
        return False

    anomalies = anomaly_data.get("anomalies", [])
    summary = anomaly_data.get("summary", "")
    check_time = anomaly_data.get("check_time", "")

    if not anomalies:
        logger.info("盘中无异动，保持静默")
        return False

    elements = []

    # 标题
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"**🔔 盘中异动提醒 - {check_time}**\n"
                       f"检测到{len(anomalies)}起异动：{summary}"
        }
    })

    # 按类型分组显示
    type_groups = {}
    for anomaly in anomalies:
        atype = anomaly.get("type", "其他")
        if atype not in type_groups:
            type_groups[atype] = []
        type_groups[atype].append(anomaly)

    for atype, group_anomalies in type_groups.items():
        elements.append({"tag": "hr"})
        level = group_anomalies[0].get("level", "medium")
        level_emoji = "🔴" if level == "high" else "🟡" if level == "medium" else "🟢"

        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{level_emoji} {atype}（{len(group_anomalies)}起）**"
            }
        })

        for anomaly in group_anomalies[:5]:  # 每种类型最多显示5条
            description = anomaly.get("description", "")
            reason = anomaly.get("reason", "暂未确认。")

            content = f"• {description}\n"
            content += f"  原因分析: {reason}"

            # 显示相关股票信息
            if anomaly.get("name"):
                code = anomaly.get("code", "")
                name = anomaly.get("name", "")
                pct = anomaly.get("pct_change", 0)
                content += f"\n  相关股票: {name}({code}) {pct:+.1f}%"

            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": content
                }
            })

    # 底部提示
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "elements": [
            {
                "tag": "plain_text",
                "content": "⚠️ 盘中异动为事件驱动提醒，仅供参考，不构成投资建议。无法确认原因时已标注'暂未确认'。"
            }
        ]
    })

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"🔔 盘中异动提醒（{len(anomalies)}起）"
                },
                "template": "red"
            },
            "elements": elements
        }
    }

    if Config.FEISHU_SECRET:
        timestamp = int(time.time())
        payload["timestamp"] = str(timestamp)
        payload["sign"] = gen_sign(Config.FEISHU_SECRET, timestamp)

    try:
        resp = requests.post(url, json=payload, timeout=15)
        result = resp.json()
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            logger.info(f"盘中异动飞书推送成功，共{len(anomalies)}起")
            return True
        else:
            logger.error(f"盘中异动飞书推送失败: {result}")
            return False
    except Exception as e:
        logger.error(f"盘中异动飞书推送异常: {e}")
        return False
