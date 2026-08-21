"""
技术指标计算模块
优先使用 pandas-ta，关键指标提供纯 pandas 实现作为 fallback
"""
import logging
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

try:
    import pandas_ta as ta
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False
    logger.warning("pandas-ta 未安装，使用内置指标计算")


def calc_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
    """计算 MACD"""
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    dif = ema_fast - ema_slow
    dea = calc_ema(dif, signal)
    macd_hist = (dif - dea) * 2
    return {
        "dif": dif.iloc[-1],
        "dea": dea.iloc[-1],
        "macd": macd_hist.iloc[-1],
        "dif_series": dif,
        "dea_series": dea,
        "macd_series": macd_hist,
        "golden_cross": dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2],
        "death_cross": dif.iloc[-1] < dea.iloc[-1] and dif.iloc[-2] >= dea.iloc[-2],
    }


def calc_rsi(close: pd.Series, period: int = 14) -> float:
    """计算 RSI"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]


def calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9, m1: int = 3, m2: int = 3) -> Dict:
    """计算 KDJ"""
    lowest_low = low.rolling(window=n).min()
    highest_high = high.rolling(window=n).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low) * 100
    k = rsv.ewm(com=m1 - 1, adjust=False).mean()
    d = k.ewm(com=m2 - 1, adjust=False).mean()
    j = 3 * k - 2 * d
    return {
        "k": k.iloc[-1],
        "d": d.iloc[-1],
        "j": j.iloc[-1],
        "golden_cross": k.iloc[-1] > d.iloc[-1] and k.iloc[-2] <= d.iloc[-2],
        "death_cross": k.iloc[-1] < d.iloc[-1] and k.iloc[-2] >= d.iloc[-2],
        "overbought": k.iloc[-1] > 80,
        "oversold": k.iloc[-1] < 20,
    }


def calc_bollinger(close: pd.Series, period: int = 20, std_dev: int = 2) -> Dict:
    """计算布林带"""
    mid = calc_sma(close, period)
    std = close.rolling(window=period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return {
        "upper": upper.iloc[-1],
        "mid": mid.iloc[-1],
        "lower": lower.iloc[-1],
        "width": (upper.iloc[-1] - lower.iloc[-1]) / mid.iloc[-1] * 100,
        "position": (close.iloc[-1] - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1]) * 100,
    }


def calc_support_resistance(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 60) -> Dict:
    """计算支撑位和压力位（近期高低点 + 均线）"""
    recent_high = high.tail(period).max()
    recent_low = low.tail(period).min()
    ma20 = calc_sma(close, 20).iloc[-1]
    ma60 = calc_sma(close, 60).iloc[-1] if len(close) >= 60 else None

    current = close.iloc[-1]
    # 压力位：当前价上方的关键位
    resistances = sorted([r for r in [recent_high, ma20, ma60] if r and r > current])
    # 支撑位：当前价下方的关键位
    supports = sorted([s for s in [recent_low, ma20, ma60] if s and s < current], reverse=True)

    return {
        "resistance_1": resistances[0] if resistances else None,
        "resistance_2": resistances[1] if len(resistances) > 1 else None,
        "support_1": supports[0] if supports else None,
        "support_2": supports[1] if len(supports) > 1 else None,
        "recent_high": recent_high,
        "recent_low": recent_low,
    }


def calc_trend(close: pd.Series) -> Dict:
    """判断趋势方向"""
    ma5 = calc_sma(close, 5)
    ma10 = calc_sma(close, 10)
    ma20 = calc_sma(close, 20)
    ma60 = calc_sma(close, 60) if len(close) >= 60 else ma20

    current = close.iloc[-1]
    # 均线多头排列
    bullish_alignment = ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1]
    # 均线空头排列
    bearish_alignment = ma5.iloc[-1] < ma10.iloc[-1] < ma20.iloc[-1]
    # 价格在均线上方
    above_ma20 = current > ma20.iloc[-1]
    above_ma60 = current > ma60.iloc[-1]

    if bullish_alignment and above_ma20:
        trend = "上升趋势"
        trend_score = 80
    elif above_ma20 and ma5.iloc[-1] > ma20.iloc[-1]:
        trend = "偏强震荡"
        trend_score = 60
    elif bearish_alignment:
        trend = "下降趋势"
        trend_score = 20
    elif not above_ma20:
        trend = "偏弱震荡"
        trend_score = 40
    else:
        trend = "横盘震荡"
        trend_score = 50

    return {
        "trend": trend,
        "trend_score": trend_score,
        "ma5": round(ma5.iloc[-1], 2),
        "ma10": round(ma10.iloc[-1], 2),
        "ma20": round(ma20.iloc[-1], 2),
        "ma60": round(ma60.iloc[-1], 2) if ma60 is not None else None,
        "bullish_alignment": bullish_alignment,
        "bearish_alignment": bearish_alignment,
    }


def calc_volume_analysis(volume: pd.Series, amount: pd.Series = None) -> Dict:
    """量能分析"""
    vol_ma5 = calc_sma(volume, 5)
    vol_ma10 = calc_sma(volume, 10)
    current_vol = volume.iloc[-1]
    ratio = current_vol / vol_ma5.iloc[-1] if vol_ma5.iloc[-1] > 0 else 1

    if ratio > 2:
        vol_status = "显著放量"
    elif ratio > 1.5:
        vol_status = "温和放量"
    elif ratio < 0.5:
        vol_status = "显著缩量"
    elif ratio < 0.7:
        vol_status = "温和缩量"
    else:
        vol_status = "量能正常"

    return {
        "current_volume": current_vol,
        "vol_ma5": round(vol_ma5.iloc[-1], 0),
        "vol_ma10": round(vol_ma10.iloc[-1], 0),
        "volume_ratio": round(ratio, 2),
        "volume_status": vol_status,
    }


def analyze_technicals(df: pd.DataFrame) -> Dict[str, Any]:
    """
    综合技术面分析
    输入：包含 date/open/high/low/close/volume 列的 DataFrame
    输出：技术指标字典
    """
    if df is None or df.empty or len(df) < 20:
        return {"error": "数据不足，无法进行技术分析"}

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    result = {}

    # 趋势
    result["trend"] = calc_trend(close)

    # MACD
    result["macd"] = {k: round(v, 4) if isinstance(v, (int, float)) else v
                      for k, v in calc_macd(close).items() if "series" not in k}

    # RSI
    rsi = calc_rsi(close)
    result["rsi"] = {
        "value": round(rsi, 2),
        "status": "超买" if rsi > 70 else ("超卖" if rsi < 30 else "正常"),
    }

    # KDJ
    result["kdj"] = {k: round(v, 2) if isinstance(v, (int, float)) else v
                     for k, v in calc_kdj(high, low, close).items()}

    # 布林带
    result["bollinger"] = {k: round(v, 2) if isinstance(v, (int, float)) else v
                           for k, v in calc_bollinger(close).items()}

    # 支撑压力
    result["support_resistance"] = {k: round(v, 2) if isinstance(v, (int, float)) else v
                                    for k, v in calc_support_resistance(high, low, close).items()}

    # 量能
    result["volume"] = calc_volume_analysis(volume)

    # 综合技术评分
    result["technical_score"] = calc_technical_score(result)

    return result


def calc_technical_score(tech: Dict) -> int:
    """
    综合技术面评分 0-100
    """
    score = 50  # 基准分

    # 趋势（权重 30%）
    score += (tech["trend"]["trend_score"] - 50) * 0.3

    # MACD（权重 20%）
    if tech["macd"].get("golden_cross"):
        score += 10
    elif tech["macd"].get("death_cross"):
        score -= 10
    if tech["macd"]["dif"] > tech["macd"]["dea"]:
        score += 5
    else:
        score -= 5

    # RSI（权重 15%）
    rsi_val = tech["rsi"]["value"]
    if 40 <= rsi_val <= 60:
        score += 3
    elif rsi_val > 70:
        score -= 8
    elif rsi_val < 30:
        score += 5  # 超卖可能反弹

    # KDJ（权重 15%）
    if tech["kdj"].get("golden_cross"):
        score += 8
    elif tech["kdj"].get("death_cross"):
        score -= 8
    if tech["kdj"].get("oversold"):
        score += 5
    elif tech["kdj"].get("overbought"):
        score -= 5

    # 布林带位置（权重 10%）
    boll_pos = tech["bollinger"]["position"]
    if 20 <= boll_pos <= 80:
        score += 3
    elif boll_pos > 90:
        score -= 5
    elif boll_pos < 10:
        score += 4

    # 量能（权重 10%）
    vol_ratio = tech["volume"]["volume_ratio"]
    if 0.8 <= vol_ratio <= 1.5:
        score += 3
    elif vol_ratio > 2 and tech["trend"]["trend_score"] > 50:
        score += 5  # 放量上涨
    elif vol_ratio > 2 and tech["trend"]["trend_score"] < 50:
        score -= 5  # 放量下跌

    return max(0, min(100, round(score)))
