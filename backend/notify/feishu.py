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

    # 自选股摘要 + 交易信号
    valid_analyses = [a for a in analyses if "error" not in a]
    if valid_analyses:
        summary_lines = []
        buy_list = []
        sell_list = []
        for a in valid_analyses[:8]:
            emoji = "🟢" if a.get("total_score", 50) >= 60 else ("🔴" if a.get("total_score", 50) < 40 else "🟡")
            # 交易信号
            ts = a.get("trading_signal", {})
            signal = ts.get("action", a.get("action", ""))
            signal_emoji = "🟩" if "买" in signal else ("🟥" if "卖" in signal else "⬜")
            conf = ts.get("confidence", 0)
            summary_lines.append(
                f"{emoji} **{a.get('name','')}**({a.get('code','')}) "
                f"{a.get('price',0)}元 {a.get('pct_change',0):+.1f}% | "
                f"评分{a.get('total_score',0)} | {signal_emoji}{signal}"
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

        # 买卖信号汇总
        if buy_list or sell_list:
            elements.append({"tag": "hr"})
            if buy_list:
                buy_lines = []
                for a in buy_list[:5]:
                    ts = a.get("trading_signal", {})
                    reasons = "、".join(ts.get("buy_signals", [])[:3])
                    buy_lines.append(f"• **{a['name']}**({a['code']}) {a['price']}元 | 置信度{ts.get('confidence',0)}% | {reasons}")
                elements.append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**🟩 买入信号（{len(buy_list)}只）**\n" + "\n".join(buy_lines)
                    }
                })
            if sell_list:
                sell_lines = []
                for a in sell_list[:5]:
                    ts = a.get("trading_signal", {})
                    reasons = "、".join(ts.get("sell_signals", [])[:3])
                    sell_lines.append(f"• **{a['name']}**({a['code']}) {a['price']}元 | 置信度{ts.get('confidence',0)}% | {reasons}")
                elements.append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**🟥 卖出信号（{len(sell_list)}只）**\n" + "\n".join(sell_lines)
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
            top_lines.append(
                f"{i+1}. {resonance_tag} **{c['name']}**({c['code']}) {c['price']}元 "
                f"{c['pct_change']:+.1f}% | 命中{c['strategy_count']}策略 | 均分{c['avg_score']}"
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
                pick_lines.append(
                    f"• **{c['name']}**({c['code']}) {c['price']}元 "
                    f"{c['pct_change']:+.1f}% | 命中{c['strategy_count']}策略 | 均分{c['avg_score']}"
                )
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "\n".join(pick_lines)
                }
            })

    # 各策略精选（每个策略前3名）
    if screener and screener.get("strategies"):
        strategy_names = {
            "low_price": "低价潜力",
            "technical_pattern": "技术形态",
            "capital_flow": "资金流入",
            "fundamental": "基本面优",
            "concept_hotspot": "概念热点",
        }
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**📊 各策略精选（前3名）**"
            }
        })
        for sname, sresults in screener["strategies"].items():
            if sresults:
                strategy_lines = []
                for i, top in enumerate(sresults[:3]):
                    strategy_lines.append(
                        f"  {i+1}. {top['name']}({top['code']}) {top['price']}元 "
                        f"{top['pct_change']:+.1f}% 评分{top['score']}"
                    )
                elements.append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**{strategy_names.get(sname, sname)}**（{len(sresults)}只）\n" + "\n".join(strategy_lines)
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
