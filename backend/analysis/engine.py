"""
五维综合分析引擎
整合技术面、基本面、资金面、概念热点、LLM深度分析
"""
import logging
from typing import Dict, Any
from datetime import datetime
from backend.data.collector import collector
from backend.analysis.technical import analyze_technical
from backend.analysis.fundamental import analyze_fundamental
from backend.analysis.capital_flow import analyze_capital_flow
from backend.analysis.concept import analyze_concept
from backend.analysis.llm_analyzer import llm_deep_analyze
from backend.analysis.signals import generate_trading_signal
from backend.analysis.three_locks import three_locks_analyzer
from backend.analysis.trend_analysis import trend_analyzer
from backend.utils.helpers import normalize_stock_code, now_str

logger = logging.getLogger(__name__)

# 各维度权重
WEIGHTS = {
    "technical": 0.30,   # 技术面 30%
    "fundamental": 0.25, # 基本面 25%
    "capital": 0.20,     # 资金面 20%
    "concept": 0.15,     # 概念热点 15%
    "llm": 0.10,         # LLM 综合 10%（可选）
}


def analyze_stock(code: str) -> Dict[str, Any]:
    """
    对单只股票进行五维综合分析
    """
    code = normalize_stock_code(code)
    logger.info(f"开始分析股票: {code}")

    # 获取基本信息
    quote = collector.get_realtime_quote(code)
    stock_info = quote or {"code": code, "name": code, "price": 0, "pct_change": 0}

    # 五维分析
    technical = analyze_technical(code)
    fundamental = analyze_fundamental(code)
    capital = analyze_capital_flow(code)
    concept = analyze_concept(code)

    # 交易信号（基于K线技术指标，给出明确买卖建议）
    kline = collector.get_daily_kline(code, days=60)
    trading_signal = generate_trading_signal(kline, stock_info)

    # 三把锁分析（趋势锁+股性锁+资金锁）
    try:
        three_locks = three_locks_analyzer.analyze(kline, stock_info, capital)
    except Exception as e:
        logger.debug(f"三把锁分析失败 {code}: {e}")
        three_locks = None

    # 走势分析（趋势/支撑压力/形态/量价）
    try:
        trend_analysis = trend_analyzer.analyze(kline, stock_info)
    except Exception as e:
        logger.debug(f"走势分析失败 {code}: {e}")
        trend_analysis = None

    # LLM 深度分析（可选）
    llm_result = llm_deep_analyze(stock_info, technical, fundamental, capital, concept)

    # 综合评分
    tech_score = technical.get("technical_score", technical.get("score", 50))
    fund_score = fundamental.get("score", 50)
    cap_score = capital.get("score", 50)
    concept_score = concept.get("score", 50)

    total_score = (
        tech_score * WEIGHTS["technical"] +
        fund_score * WEIGHTS["fundamental"] +
        cap_score * WEIGHTS["capital"] +
        concept_score * WEIGHTS["concept"]
    )

    # LLM 加分/减分（如果有）
    llm_adjustment = 0
    if llm_result:
        # 简单根据 LLM 建议调整
        suggestion = llm_result.get("suggestion", "").lower()
        if "买入" in suggestion or "加仓" in suggestion:
            llm_adjustment = 5
        elif "卖出" in suggestion or "减仓" in suggestion:
            llm_adjustment = -5
        total_score = total_score * 0.9 + (50 + llm_adjustment) * 0.1

    total_score = round(max(0, min(100, total_score)))

    # 综合评级
    if total_score >= 75:
        rating = "强烈看多"
        action = "买入"
    elif total_score >= 60:
        rating = "偏多"
        action = "逢低关注"
    elif total_score >= 45:
        rating = "中性"
        action = "观望"
    elif total_score >= 30:
        rating = "偏空"
        action = "减仓"
    else:
        rating = "强烈看空"
        action = "卖出"

    # 风险提示
    risks = []
    if tech_score < 40:
        risks.append("技术面走弱")
    if fund_score < 40:
        risks.append("基本面偏弱")
    if cap_score < 40:
        risks.append("主力资金流出")
    if concept_score < 40:
        risks.append("缺乏热点催化")
    if stock_info.get("pct_change", 0) > 9:
        risks.append("短期涨幅过大，注意回调风险")

    result = {
        "code": code,
        "name": stock_info.get("name", code),
        "price": stock_info.get("price", 0),
        "pct_change": stock_info.get("pct_change", 0),
        "analysis_time": now_str(),
        "total_score": total_score,
        "rating": rating,
        "action": action,
        "scores": {
            "technical": tech_score,
            "fundamental": fund_score,
            "capital": cap_score,
            "concept": concept_score,
        },
        "technical": technical,
        "fundamental": fundamental,
        "capital": capital,
        "concept": concept,
        "llm_analysis": llm_result,
        "trading_signal": trading_signal,
        "three_locks": three_locks,
        "trend_analysis": trend_analysis,
        "risks": risks,
    }

    logger.info(f"股票 {code} 分析完成，综合评分: {total_score}，评级: {rating}")
    return result


def analyze_batch(codes: list) -> list:
    """批量分析股票"""
    results = []
    for code in codes:
        try:
            r = analyze_stock(code)
            results.append(r)
        except Exception as e:
            logger.error(f"分析 {code} 失败: {e}")
            results.append({"code": code, "error": str(e)})
    return results
