"""
技术指标计算模块（增强版）
包含 20+ 技术指标：趋势/动量/波动率/成交量/支撑压力
优先使用 pandas-ta，关键指标提供纯 pandas 实现作为 fallback
"""
import logging
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

try:
    import pandas_ta as ta
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False
    logger.warning("pandas-ta 未安装，使用内置指标计算")


# ============ 基础均线 ============

def calc_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_ma_system(close: pd.Series) -> Dict:
    """均线系统 MA5/10/20/60/120"""
    mas = {}
    for p in [5, 10, 20, 60, 120]:
        if len(close) >= p:
            mas[f"ma{p}"] = round(calc_sma(close, p).iloc[-1], 2)
        else:
            mas[f"ma{p}"] = None
    # 多头/空头排列
    ma5 = mas.get("ma5")
    ma10 = mas.get("ma10")
    ma20 = mas.get("ma20")
    ma60 = mas.get("ma60")
    bullish = all(v is not None for v in [ma5, ma10, ma20]) and ma5 > ma10 > ma20
    bearish = all(v is not None for v in [ma5, ma10, ma20]) and ma5 < ma10 < ma20
    mas["bullish_alignment"] = bullish
    mas["bearish_alignment"] = bearish
    mas["price_above_ma20"] = close.iloc[-1] > ma20 if ma20 else None
    mas["price_above_ma60"] = close.iloc[-1] > ma60 if ma60 else None
    return mas


# ============ MACD ============

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
        "hist_increasing": macd_hist.iloc[-1] > macd_hist.iloc[-2],
        "zero_axis_above": dif.iloc[-1] > 0,
    }


# ============ RSI（多周期） ============

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


def calc_rsi_system(close: pd.Series) -> Dict:
    """RSI 多周期系统 RSI6/12/24"""
    rsi6 = calc_rsi(close, 6) if len(close) >= 7 else None
    rsi12 = calc_rsi(close, 12) if len(close) >= 13 else None
    rsi24 = calc_rsi(close, 24) if len(close) >= 25 else None
    return {
        "rsi6": round(rsi6, 2) if rsi6 else None,
        "rsi12": round(rsi12, 2) if rsi12 else None,
        "rsi24": round(rsi24, 2) if rsi24 else None,
        "status": "超买" if (rsi6 and rsi6 > 80) else ("超卖" if (rsi6 and rsi6 < 20) else "正常"),
        "golden_cross": rsi6 and rsi12 and rsi6 > rsi12 and calc_rsi(close, 6) <= calc_rsi(close, 12) if len(close) >= 13 else False,
    }


# ============ KDJ ============

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
        "j_overbought": j.iloc[-1] > 100,
        "j_oversold": j.iloc[-1] < 0,
    }


# ============ 布林带 ============

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
        "breakout_upper": close.iloc[-1] > upper.iloc[-1],
        "breakout_lower": close.iloc[-1] < lower.iloc[-1],
        "bandwidth_expanding": (upper.iloc[-1] - lower.iloc[-1]) > (upper.iloc[-2] - lower.iloc[-2]),
    }


# ============ ATR 平均真实波幅 ============

def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> Dict:
    """计算 ATR 平均真实波幅"""
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    atr_value = atr.iloc[-1]
    atr_ratio = atr_value / close.iloc[-1] * 100 if close.iloc[-1] > 0 else 0
    return {
        "atr": round(atr_value, 2),
        "atr_ratio": round(atr_ratio, 2),
        "volatility_level": "高波动" if atr_ratio > 5 else ("中波动" if atr_ratio > 2 else "低波动"),
    }


# ============ OBV 能量潮 ============

def calc_obv(close: pd.Series, volume: pd.Series) -> Dict:
    """计算 OBV 能量潮"""
    obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
    obv_ma10 = obv.rolling(window=10).mean()
    current_obv = obv.iloc[-1]
    obv_ma = obv_ma10.iloc[-1]
    return {
        "obv": round(current_obv, 0),
        "obv_ma10": round(obv_ma, 0),
        "trend_up": current_obv > obv_ma,
        "divergence_bullish": current_obv > obv_ma and close.iloc[-1] < close.iloc[-5] if len(close) >= 5 else False,
    }


# ============ Williams %R 威廉指标 ============

def calc_williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> Dict:
    """计算 Williams %R"""
    highest_high = high.rolling(window=period).max()
    lowest_low = low.rolling(window=period).min()
    wr = (highest_high - close) / (highest_high - lowest_low) * -100
    wr_value = wr.iloc[-1]
    return {
        "wr": round(wr_value, 2),
        "oversold": wr_value < -80,
        "overbought": wr_value > -20,
        "status": "超卖" if wr_value < -80 else ("超买" if wr_value > -20 else "正常"),
    }


# ============ 动量指标 ============

def calc_momentum(close: pd.Series) -> Dict:
    """动量指标 MOM/ROC"""
    mom5 = close.iloc[-1] - close.iloc[-5] if len(close) >= 5 else None
    mom10 = close.iloc[-1] - close.iloc[-10] if len(close) >= 10 else None
    mom20 = close.iloc[-1] - close.iloc[-20] if len(close) >= 20 else None
    roc5 = (close.iloc[-1] / close.iloc[-5] - 1) * 100 if len(close) >= 5 and close.iloc[-5] > 0 else None
    roc10 = (close.iloc[-1] / close.iloc[-10] - 1) * 100 if len(close) >= 10 and close.iloc[-10] > 0 else None
    roc20 = (close.iloc[-1] / close.iloc[-20] - 1) * 100 if len(close) >= 20 and close.iloc[-20] > 0 else None
    return {
        "mom5": round(mom5, 2) if mom5 else None,
        "mom10": round(mom10, 2) if mom10 else None,
        "mom20": round(mom20, 2) if mom20 else None,
        "roc5": round(roc5, 2) if roc5 else None,
        "roc10": round(roc10, 2) if roc10 else None,
        "roc20": round(roc20, 2) if roc20 else None,
        "momentum_up": roc5 > 0 if roc5 else False,
    }


# ============ 波动率 ============

def calc_volatility(close: pd.Series) -> Dict:
    """波动率分析"""
    returns = close.pct_change()
    vol5 = returns.tail(5).std() * np.sqrt(252) * 100 if len(returns) >= 5 else None
    vol10 = returns.tail(10).std() * np.sqrt(252) * 100 if len(returns) >= 10 else None
    vol20 = returns.tail(20).std() * np.sqrt(252) * 100 if len(returns) >= 20 else None
    return {
        "vol5": round(vol5, 2) if vol5 else None,
        "vol10": round(vol10, 2) if vol10 else None,
        "vol20": round(vol20, 2) if vol20 else None,
        "volatility_increasing": vol5 and vol10 and vol5 > vol10,
    }


# ============ 支撑压力位 ============

def calc_support_resistance(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 60) -> Dict:
    """计算支撑位和压力位（近期高低点 + 均线 + 枢轴点）"""
    recent_high = high.tail(period).max()
    recent_low = low.tail(period).min()
    ma20 = calc_sma(close, 20).iloc[-1]
    ma60 = calc_sma(close, 60).iloc[-1] if len(close) >= 60 else None
    current = close.iloc[-1]

    # 枢轴点 Pivot
    pivot = (recent_high + recent_low + current) / 3
    r1 = 2 * pivot - recent_low
    s1 = 2 * pivot - recent_high
    r2 = pivot + (recent_high - recent_low)
    s2 = pivot - (recent_high - recent_low)

    # 压力位：当前价上方的关键位
    resistances = sorted([r for r in [recent_high, ma20, ma60, r1, r2] if r and r > current])
    # 支撑位：当前价下方的关键位
    supports = sorted([s for s in [recent_low, ma20, ma60, s1, s2] if s and s < current], reverse=True)

    return {
        "resistance_1": resistances[0] if resistances else None,
        "resistance_2": resistances[1] if len(resistances) > 1 else None,
        "support_1": supports[0] if supports else None,
        "support_2": supports[1] if len(supports) > 1 else None,
        "pivot": round(pivot, 2),
        "recent_high": recent_high,
        "recent_low": recent_low,
    }


# ============ 趋势判断 ============

def calc_trend(close: pd.Series) -> Dict:
    """判断趋势方向（增强版）"""
    ma_system = calc_ma_system(close)
    current = close.iloc[-1]

    ma5 = ma_system.get("ma5")
    ma10 = ma_system.get("ma10")
    ma20 = ma_system.get("ma20")
    ma60 = ma_system.get("ma60")

    bullish = ma_system["bullish_alignment"]
    bearish = ma_system["bearish_alignment"]
    above_ma20 = ma_system["price_above_ma20"]
    above_ma60 = ma_system["price_above_ma60"]

    # ADX 趋势强度（简化版）
    if len(close) >= 20:
        price_change = abs(close.iloc[-1] - close.iloc[-20]) / close.iloc[-20] * 100
        trend_strength = min(100, price_change * 5)
    else:
        trend_strength = 50

    if bullish and above_ma20 and above_ma60:
        trend = "强势上升"
        trend_score = 90
    elif bullish and above_ma20:
        trend = "上升趋势"
        trend_score = 75
    elif above_ma20 and ma5 > ma20:
        trend = "偏强震荡"
        trend_score = 60
    elif bearish:
        trend = "下降趋势"
        trend_score = 20
    elif not above_ma20:
        trend = "偏弱震荡"
        trend_score = 35
    else:
        trend = "横盘震荡"
        trend_score = 50

    return {
        "trend": trend,
        "trend_score": trend_score,
        "trend_strength": round(trend_strength, 1),
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma60": ma60,
        "ma120": ma_system.get("ma120"),
        "bullish_alignment": bullish,
        "bearish_alignment": bearish,
    }


# ============ 量能分析 ============

def calc_volume_analysis(volume: pd.Series, close: pd.Series = None) -> Dict:
    """量能分析（增强版，含量价配合）"""
    vol_ma5 = calc_sma(volume, 5)
    vol_ma10 = calc_sma(volume, 10)
    vol_ma20 = calc_sma(volume, 20) if len(volume) >= 20 else vol_ma10
    current_vol = volume.iloc[-1]
    ratio = current_vol / vol_ma5.iloc[-1] if vol_ma5.iloc[-1] > 0 else 1

    if ratio > 3:
        vol_status = "巨量"
    elif ratio > 2:
        vol_status = "显著放量"
    elif ratio > 1.5:
        vol_status = "温和放量"
    elif ratio < 0.5:
        vol_status = "显著缩量"
    elif ratio < 0.7:
        vol_status = "温和缩量"
    else:
        vol_status = "量能正常"

    # 量价配合
    volume_price = "未知"
    if close is not None and len(close) >= 2:
        price_up = close.iloc[-1] > close.iloc[-2]
        if ratio > 1.5 and price_up:
            volume_price = "放量上涨（健康）"
        elif ratio > 1.5 and not price_up:
            volume_price = "放量下跌（警惕）"
        elif ratio < 0.7 and price_up:
            volume_price = "缩量上涨（观望）"
        elif ratio < 0.7 and not price_up:
            volume_price = "缩量下跌（企稳）"
        else:
            volume_price = "量价配合正常"

    return {
        "current_volume": current_vol,
        "vol_ma5": round(vol_ma5.iloc[-1], 0),
        "vol_ma10": round(vol_ma10.iloc[-1], 0),
        "vol_ma20": round(vol_ma20.iloc[-1], 0),
        "volume_ratio": round(ratio, 2),
        "volume_status": vol_status,
        "volume_price": volume_price,
    }


# ============ 综合技术面分析 ============

def analyze_technicals(df: pd.DataFrame) -> Dict[str, Any]:
    """
    综合技术面分析（增强版，20+指标）
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

    # 1. 趋势
    result["trend"] = calc_trend(close)

    # 2. 均线系统
    result["ma_system"] = calc_ma_system(close)

    # 3. MACD
    result["macd"] = {k: round(v, 4) if isinstance(v, (int, float)) else v
                      for k, v in calc_macd(close).items() if "series" not in k}

    # 4. RSI 多周期
    result["rsi"] = calc_rsi_system(close)

    # 5. KDJ
    result["kdj"] = {k: round(v, 2) if isinstance(v, (int, float)) else v
                     for k, v in calc_kdj(high, low, close).items()}

    # 6. 布林带
    result["bollinger"] = {k: round(v, 2) if isinstance(v, (int, float)) else v
                           for k, v in calc_bollinger(close).items()}

    # 7. ATR
    result["atr"] = calc_atr(high, low, close)

    # 8. OBV
    result["obv"] = calc_obv(close, volume)

    # 9. Williams %R
    result["williams"] = calc_williams_r(high, low, close)

    # 10. 动量
    result["momentum"] = calc_momentum(close)

    # 11. 波动率
    result["volatility"] = calc_volatility(close)

    # 12. 支撑压力
    result["support_resistance"] = {k: round(v, 2) if isinstance(v, (int, float)) else v
                                    for k, v in calc_support_resistance(high, low, close).items()}

    # 13. 量能
    result["volume"] = calc_volume_analysis(volume, close)

    # 14. 综合技术评分
    result["technical_score"] = calc_technical_score(result)

    # 15. 技术信号汇总
    result["signals"] = detect_signals(result)

    return result


# ============ 信号检测 ============

def detect_signals(tech: Dict) -> List[Dict]:
    """检测技术信号（12+类型）"""
    signals = []

    # 1. MACD 金叉/死叉
    if tech["macd"].get("golden_cross"):
        signals.append({"type": "MACD金叉", "direction": "bullish", "strength": 80})
    if tech["macd"].get("death_cross"):
        signals.append({"type": "MACD死叉", "direction": "bearish", "strength": 80})

    # 2. KDJ 金叉/死叉
    if tech["kdj"].get("golden_cross"):
        signals.append({"type": "KDJ金叉", "direction": "bullish", "strength": 70})
    if tech["kdj"].get("death_cross"):
        signals.append({"type": "KDJ死叉", "direction": "bearish", "strength": 70})

    # 3. KDJ 超卖/超买
    if tech["kdj"].get("oversold"):
        signals.append({"type": "KDJ超卖（反弹机会）", "direction": "bullish", "strength": 60})
    if tech["kdj"].get("overbought"):
        signals.append({"type": "KDJ超买（回调风险）", "direction": "bearish", "strength": 60})

    # 4. RSI 超卖/超买
    rsi6 = tech["rsi"].get("rsi6")
    if rsi6 and rsi6 < 20:
        signals.append({"type": "RSI超卖（反弹机会）", "direction": "bullish", "strength": 65})
    if rsi6 and rsi6 > 80:
        signals.append({"type": "RSI超买（回调风险）", "direction": "bearish", "strength": 65})

    # 5. 均线交叉
    ma = tech["ma_system"]
    if ma.get("ma5") and ma.get("ma10") and ma.get("ma20"):
        if ma["bullish_alignment"]:
            signals.append({"type": "均线多头排列", "direction": "bullish", "strength": 75})
        if ma["bearish_alignment"]:
            signals.append({"type": "均线空头排列", "direction": "bearish", "strength": 75})

    # 6. 布林带突破
    if tech["bollinger"].get("breakout_upper"):
        signals.append({"type": "突破布林上轨（强势）", "direction": "bullish", "strength": 70})
    if tech["bollinger"].get("breakout_lower"):
        signals.append({"type": "跌破布林下轨（弱势）", "direction": "bearish", "strength": 70})

    # 7. 放量
    if tech["volume"]["volume_ratio"] > 2:
        direction = "bullish" if tech["trend"]["trend_score"] > 50 else "bearish"
        signals.append({"type": f"放量（{tech['volume']['volume_ratio']}倍）", "direction": direction, "strength": 60})

    # 8. OBV 趋势
    if tech["obv"].get("trend_up") and tech["trend"]["trend_score"] < 50:
        signals.append({"type": "OBV底背离（看涨）", "direction": "bullish", "strength": 75})

    # 9. Williams 超卖
    if tech["williams"].get("oversold"):
        signals.append({"type": "Williams超卖（反弹机会）", "direction": "bullish", "strength": 55})

    # 10. 动量
    if tech["momentum"].get("roc5") and tech["momentum"]["roc5"] > 5:
        signals.append({"type": "短期动量强劲", "direction": "bullish", "strength": 65})
    if tech["momentum"].get("roc5") and tech["momentum"]["roc5"] < -5:
        signals.append({"type": "短期动量衰弱", "direction": "bearish", "strength": 65})

    # 11. 波动率扩张
    if tech["volatility"].get("volatility_increasing") and tech["trend"]["trend_score"] > 60:
        signals.append({"type": "波动率扩张+上升趋势（加速）", "direction": "bullish", "strength": 70})

    # 12. 趋势突破
    if tech["trend"]["trend"] == "强势上升":
        signals.append({"type": "强势上升趋势", "direction": "bullish", "strength": 85})

    return signals


# ============ 综合技术评分 ============

def calc_technical_score(tech: Dict) -> int:
    """
    综合技术面评分 0-100（增强版，多维度加权）
    """
    score = 50  # 基准分

    # 1. 趋势（权重 25%）
    score += (tech["trend"]["trend_score"] - 50) * 0.25

    # 2. MACD（权重 15%）
    if tech["macd"].get("golden_cross"):
        score += 8
    elif tech["macd"].get("death_cross"):
        score -= 8
    if tech["macd"]["dif"] > tech["macd"]["dea"]:
        score += 4
    else:
        score -= 4
    if tech["macd"].get("hist_increasing") and tech["macd"]["dif"] > 0:
        score += 3

    # 3. RSI（权重 10%）
    rsi_val = tech["rsi"].get("rsi6") or 50
    if 40 <= rsi_val <= 60:
        score += 3
    elif rsi_val > 80:
        score -= 8
    elif rsi_val < 20:
        score += 5  # 超卖可能反弹

    # 4. KDJ（权重 10%）
    if tech["kdj"].get("golden_cross"):
        score += 6
    elif tech["kdj"].get("death_cross"):
        score -= 6
    if tech["kdj"].get("oversold"):
        score += 4
    elif tech["kdj"].get("overbought"):
        score -= 4

    # 5. 布林带位置（权重 10%）
    boll_pos = tech["bollinger"]["position"]
    if 20 <= boll_pos <= 80:
        score += 3
    elif boll_pos > 95:
        score -= 6
    elif boll_pos < 5:
        score += 4

    # 6. 量能（权重 10%）
    vol_ratio = tech["volume"]["volume_ratio"]
    vp = tech["volume"].get("volume_price", "")
    if "放量上涨" in vp:
        score += 6
    elif "放量下跌" in vp:
        score -= 6
    elif "缩量下跌" in vp:
        score += 3  # 缩量下跌可能企稳
    elif 0.8 <= vol_ratio <= 1.5:
        score += 2

    # 7. 均线系统（权重 10%）
    if tech["ma_system"].get("bullish_alignment"):
        score += 6
    elif tech["ma_system"].get("bearish_alignment"):
        score -= 6
    if tech["ma_system"].get("price_above_ma60"):
        score += 3
    else:
        score -= 2

    # 8. OBV（权重 5%）
    if tech["obv"].get("trend_up"):
        score += 3
    else:
        score -= 2

    # 9. 动量（权重 5%）
    roc5 = tech["momentum"].get("roc5")
    if roc5 and roc5 > 3:
        score += 3
    elif roc5 and roc5 < -3:
        score -= 3

    return max(0, min(100, round(score)))
