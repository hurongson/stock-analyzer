"""
报告生成模块
将分析结果生成为结构化 JSON + Markdown 文本
"""
import os
import json
import logging
from typing import Dict, List
from datetime import datetime
from backend.config import Config
from backend.utils.helpers import today_str, save_json

logger = logging.getLogger(__name__)


def generate_stock_report(analysis: Dict) -> str:
    """生成单只股票的 Markdown 分析报告"""
    lines = []
    name = analysis.get("name", analysis.get("code", ""))
    code = analysis.get("code", "")
    price = analysis.get("price", 0)
    pct = analysis.get("pct_change", 0)
    score = analysis.get("total_score", 0)
    rating = analysis.get("rating", "")
    action = analysis.get("action", "")

    lines.append(f"## {name}({code})")
    lines.append(f"**现价**: {price} | **涨跌幅**: {pct:+.2f}% | **综合评分**: {score}/100 | **评级**: {rating}")
    lines.append(f"**操作建议**: {action}")
    lines.append("")

    # 五维评分
    scores = analysis.get("scores", {})
    lines.append("### 五维评分")
    lines.append(f"| 维度 | 评分 |")
    lines.append(f"|------|------|")
    lines.append(f"| 技术面 | {scores.get('technical', 50)} |")
    lines.append(f"| 基本面 | {scores.get('fundamental', 50)} |")
    lines.append(f"| 资金面 | {scores.get('capital', 50)} |")
    lines.append(f"| 概念热点 | {scores.get('concept', 50)} |")
    lines.append("")

    # 技术面
    tech = analysis.get("technical", {})
    if tech and "conclusions" in tech:
        lines.append("### 技术面")
        for c in tech["conclusions"][:6]:
            lines.append(f"- {c}")
        lines.append("")

    # 基本面
    fund = analysis.get("fundamental", {})
    if fund and "conclusions" in fund:
        lines.append("### 基本面")
        for c in fund["conclusions"][:5]:
            lines.append(f"- {c}")
        lines.append("")

    # 资金面
    cap = analysis.get("capital", {})
    if cap and "conclusions" in cap:
        lines.append("### 资金面")
        for c in cap["conclusions"][:4]:
            lines.append(f"- {c}")
        lines.append("")

    # 概念热点
    concept = analysis.get("concept", {})
    if concept and "conclusions" in concept:
        lines.append("### 概念热点")
        for c in concept["conclusions"][:3]:
            lines.append(f"- {c}")
        lines.append("")

    # LLM 深度分析
    llm = analysis.get("llm_analysis")
    if llm and llm.get("raw"):
        lines.append("### AI 深度分析")
        lines.append(llm["raw"])
        lines.append("")

    # 风险提示
    risks = analysis.get("risks", [])
    if risks:
        lines.append("### ⚠️ 风险提示")
        for r in risks:
            lines.append(f"- {r}")
        lines.append("")

    lines.append("---")
    return "\n".join(lines)


def _format_points(c: Dict) -> str:
    """取 trading_signal 中的买入/卖出/止损/目标价，拼成 markdown 片段（与飞书同源）"""
    ts = c.get("trading_signal") or {}
    seg = []
    for label, key in (("买", "buy_price"), ("卖", "sell_price"),
                       ("止损", "stop_loss"), ("目标", "target_price")):
        if ts.get(key) is not None:
            seg.append(f"{label}{ts[key]}")
    return " / ".join(seg)


def generate_daily_report(stock_analyses: List[Dict], screener_result: Dict = None,
                          reverse_screen_result: Dict = None) -> Dict:
    """
    生成每日综合报告
    返回包含 markdown 和 json 的字典
    """
    date = today_str()
    lines = [f"# 📈 股票分析日报 - {date}", ""]

    # 自选股分析摘要
    lines.append("## 自选股分析摘要")
    lines.append("")
    lines.append("| 股票 | 现价 | 涨跌幅 | 评分 | 评级 | 操作建议 |")
    lines.append("|------|------|--------|------|------|----------|")
    for a in stock_analyses:
        if "error" in a:
            continue
        lines.append(
            f"| {a.get('name','')}({a.get('code','')}) | {a.get('price',0)} | "
            f"{a.get('pct_change',0):+.2f}% | {a.get('total_score',0)} | "
            f"{a.get('rating','')} | {a.get('action','')} |"
        )
    lines.append("")

    # 详细分析
    lines.append("## 详细分析")
    lines.append("")
    for a in stock_analyses:
        if "error" in a:
            lines.append(f"### {a.get('code', '')} 分析失败: {a.get('error', '')}")
            continue
        lines.append(generate_stock_report(a))

    # 选股结果
    if screener_result and "combined" in screener_result:
        lines.append("## 🎯 选股推荐")
        lines.append("")
        combined = screener_result["combined"]
        if combined:
            lines.append("### 多策略共振（重点关注）")
            resonance = [c for c in combined if c.get("resonance")]
            if resonance:
                lines.append("| 股票 | 现价 | 涨跌幅 | 命中策略 | 均分 | 理由 |")
                lines.append("|------|------|--------|----------|------|------|")
                for c in resonance[:10]:
                    lines.append(
                        f"| {c['name']}({c['code']}) | {c['price']} | {c['pct_change']:+.2f}% | "
                        f"{c['strategy_count']}个 | {c['avg_score']} | {'; '.join(c['strategies'])} |"
                    )
                lines.append("")

            # 各策略精选
            strategies = screener_result.get("strategies", {})
            strategy_names = {
                "low_price": "低价潜力股",
                "technical_pattern": "技术形态选股",
                "capital_flow": "资金面选股",
                "fundamental": "基本面选股",
                "concept_hotspot": "概念热点选股",
            }
            for sname, sresults in strategies.items():
                if sresults:
                    lines.append(f"### {strategy_names.get(sname, sname)} TOP5")
                    lines.append("| 股票 | 现价 | 涨跌幅 | 评分 | 理由 |")
                    lines.append("|------|------|--------|------|------|")
                    for r in sresults[:5]:
                        reason_short = r["reason"][:50] + "..." if len(r["reason"]) > 50 else r["reason"]
                        lines.append(
                            f"| {r['name']}({r['code']}) | {r['price']} | "
                            f"{r['pct_change']:+.2f}% | {r['score']} | {reason_short} |"
                        )
                    lines.append("")

        # 特别推荐（重点关注）
        if screener_result.get("special_picks"):
            lines.append("### ⭐ 特别推荐（重点关注）")
            for i, c in enumerate(screener_result["special_picks"], 1):
                lines.append(
                    f"{i}. **{c['name']}**({c['code']}) {c['price']}元 "
                    f"{c['pct_change']:+.2f}% | 评分{c.get('avg_score', 0)} | {_format_points(c)}"
                )
                if c.get("special_reasons"):
                    lines.append(f"   - 原因: {'、'.join(c['special_reasons'][:3])}")
            lines.append("")

        # 陈小群风格特别推荐
        if screener_result.get("chen_xiaoqun_picks"):
            lines.append("### 🔥 陈小群风格特别推荐（板块合力+量价市值+四类有效涨停）")
            lines.append("> 买在分歧、卖在一致、死守主线、只做真龙")
            for i, c in enumerate(screener_result["chen_xiaoqun_picks"], 1):
                lines.append(
                    f"{i}. 🔥 **{c['name']}**({c['code']}) {c['price']}元 "
                    f"{c['pct_change']:+.2f}% | 陈小群评分{c.get('chen_xiaoqun_score', 0)} | {_format_points(c)}"
                )
                if c.get("chen_xiaoqun_reasons"):
                    lines.append(f"   - 理由: {'、'.join(c['chen_xiaoqun_reasons'][:3])}")
            lines.append("")

        # 涨停预测
        if screener_result.get("limit_up_picks"):
            lines.append("### 🔥 涨停预测（未来1-3天关注）")
            for i, c in enumerate(screener_result["limit_up_picks"], 1):
                prob = c.get("limit_up_probability", 0)
                prob_s = f"{prob:.0f}%" if isinstance(prob, (int, float)) else str(prob)
                lines.append(
                    f"{i}. **{c['name']}**({c['code']}) {c['price']}元 "
                    f"{c['pct_change']:+.2f}% | 涨停概率{prob_s} | {_format_points(c)}"
                )
                if c.get("limit_up_reasons"):
                    lines.append(f"   - 理由: {'、'.join(c['limit_up_reasons'][:3])}")
            lines.append("")

    # 反向筛选（空头模式）
    if reverse_screen_result and reverse_screen_result.get("total_candidates"):
        n_elim = len(reverse_screen_result.get("eliminated", []))
        n_down = len(reverse_screen_result.get("downgraded", []))
        n_kept = len(reverse_screen_result.get("kept", []))
        lines.append("## 🔍 反向筛选（空头模式）")
        lines.append(
            f"候选{reverse_screen_result.get('total_candidates')}只 | "
            f"淘汰{n_elim}只 | 降级{n_down}只 | 保留{n_kept}只"
        )
        if reverse_screen_result.get("summary"):
            lines.append(f"> {reverse_screen_result['summary']}")
        stats = reverse_screen_result.get("elimination_reasons", {})
        if stats:
            lines.append("")
            lines.append("**淘汰原因：**")
            for reason, count in sorted(stats.items(), key=lambda x: x[1], reverse=True)[:5]:
                lines.append(f"- {reason}: {count}只")
        est = reverse_screen_result.get("eliminated", [])
        if est:
            lines.append("")
            lines.append("**被淘汰股票：**")
            for s in est[:8]:
                lines.append(f"- {s.get('name')}({s.get('code')})")
        funnel = reverse_screen_result.get("three_level_funnel", {})
        if funnel:
            lines.append("")
            lines.append(
                f"**三级漏斗：** 观察池{len(funnel.get('observation_pool', []))}只 / "
                f"研究池{len(funnel.get('research_pool', []))}只 / "
                f"核心池{len(funnel.get('core_pool', []))}只"
            )
            core = funnel.get("core_pool", [])
            if core:
                lines.append("")
                lines.append("**核心池：** " + "、".join(
                    f"{s.get('name')}({s.get('code')})" for s in core))
        lines.append("")

    lines.append("---")
    lines.append("*本报告由 AI 自动生成，仅供参考，不构成投资建议。投资有风险，入市需谨慎。*")

    markdown = "\n".join(lines)

    # JSON 数据（供前端使用）
    json_data = {
        "date": date,
        "generated_at": datetime.now().isoformat(),
        "stock_analyses": stock_analyses,
        "screener_result": screener_result,
        "markdown": markdown,
    }

    return {
        "markdown": markdown,
        "json": json_data,
    }


def save_report(report: Dict, filename: str = None) -> str:
    """保存报告到文件"""
    if filename is None:
        filename = f"report_{today_str()}"

    json_path = os.path.join(Config.REPORT_DIR, f"{filename}.json")
    md_path = os.path.join(Config.REPORT_DIR, f"{filename}.md")

    save_json(report["json"], json_path)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report["markdown"])

    logger.info(f"报告已保存: {json_path}")
    return json_path
