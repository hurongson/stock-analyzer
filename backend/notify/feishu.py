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
from typing import Dict, Optional
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
        limit_up_count = len(screener.get("limit_up_picks", []))
        if combined_count > 0 or special_count > 0 or limit_up_count > 0:
            summary_parts = []
            if special_count > 0:
                summary_parts.append(f"⭐特别推荐{special_count}只")
            if limit_up_count > 0:
                summary_parts.append(f"🔥涨停预测{limit_up_count}只")
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
    # 获取精选10支和全部30支（适配新的返回结构）
    top_picks = late_day_data.get("top_picks", [])
    all_picks = late_day_data.get("all_picks", picks)
    market_timing = late_day_data.get("market_timing", {})

    # 如果没有top_picks，从all_picks中取前10只
    if not top_picks and all_picks:
        top_picks = all_picks[:10]

    if not all_picks:
        logger.info("无尾盘选股推荐，跳过推送")
        return False

    elements = []

    # 标题
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"**🎯 尾盘选股推荐 - {date} 14:30**\n"
                       f"当日买入，次日冲高卖出（T+1短线）\n"
                       f"共推荐{len(all_picks)}只，精选{len(top_picks)}只重点关注"
        }
    })

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

            content = (
                f"**{i+1}. ⭐ {p['name']}({p['code']})** {p['price']}元 {p['pct_change']:+.1f}% | 评分{score}\n"
                f"   {point_str}"
                f"{tl_str}"
                f"{news_str}"
                f"{limit_up_str}\n"
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

    # 底部
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "elements": [{
            "tag": "plain_text",
            "content": "⚠️ 尾盘选股为短线策略，仅供参考，不构成投资建议。股市有风险，投资需谨慎。"
        }]
    })

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"🎯 尾盘选股推荐 {date} 14:30"
                },
                "template": "orange"
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
