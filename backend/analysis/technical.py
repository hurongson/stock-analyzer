"""
技术面分析
"""
import logging
from typing import Dict, Any
from backend.data.collector import collector
from backend.analysis.indicators import analyze_technicals
from backend.config import Config

logger = logging.getLogger(__name__)


def analyze_technical(code: str) -> Dict[str, Any]:
    """技术面分析入口"""
    df = collector.get_daily_kline(code, days=Config.TECHNICAL_LOOKBACK_DAYS)
    if df is None or df.empty:
        return {"error": "无法获取K线数据", "score": 50}

    tech = analyze_technicals(df)
    if "error" in tech:
        return tech

    # 生成技术面结论
    conclusions = []
    trend = tech["trend"]
    macd = tech["macd"]
    rsi = tech["rsi"]
    kdj = tech["kdj"]
    boll = tech["bollinger"]
    vol = tech["volume"]

    conclusions.append(f"趋势：{trend['trend']}（MA5={trend['ma5']}, MA20={trend['ma20']}）")

    if macd.get("golden_cross"):
        conclusions.append("MACD 金叉，短期动能转强")
    elif macd.get("death_cross"):
        conclusions.append("MACD 死叉，短期动能转弱")
    elif macd["dif"] > macd["dea"]:
        conclusions.append("MACD 多头排列")
    else:
        conclusions.append("MACD 空头排列")

    conclusions.append(f"RSI={rsi['value']}（{rsi['status']}）")

    if kdj.get("golden_cross"):
        conclusions.append("KDJ 金叉")
    elif kdj.get("death_cross"):
        conclusions.append("KDJ 死叉")

    conclusions.append(f"布林带位置：{boll['position']:.0f}%，带宽{boll['width']:.1f}%")
    conclusions.append(f"量能：{vol['volume_status']}（量比{vol['volume_ratio']}）")

    sr = tech["support_resistance"]
    if sr["support_1"]:
        conclusions.append(f"支撑位：{sr['support_1']}，压力位：{sr['resistance_1']}")

    tech["conclusions"] = conclusions
    return tech
