"""
交易信号分析模块（增强版）
基于20+技术指标给出明确的买入/卖出/持有建议，以及置信度
支持市场环境过滤、多维度信号、动态买卖点位
"""
import pandas as pd
from typing import Dict, List
from backend.analysis.indicators import (
    calc_sma, calc_ema, calc_macd, calc_kdj, calc_rsi,
    calc_bollinger, calc_volume_analysis, calc_support_resistance,
    calc_atr, calc_obv, calc_williams_r, calc_momentum, calc_ma_system,
    calc_trend
)


def generate_trading_signal(kline: pd.DataFrame, quote: Dict = None,
                            market_sentiment_score: int = 50) -> Dict:
    """
    生成单只股票的交易信号（增强版）
    market_sentiment_score: 市场情绪评分 0-100，用于过滤信号
    返回: {signal, action, confidence, reasons, price, buy_price, sell_price, ...}
    """
    if kline is None or len(kline) < 20:
        return {"signal": "hold", "confidence": 0, "reasons": ["数据不足"], "score": 50}

    close = kline["close"]
    high = kline["high"]
    low = kline["low"]
    volume = kline["volume"]

    buy_signals = []
    sell_signals = []
    buy_score = 0
    sell_score = 0

    # 当前价格
    current_price = quote.get("price") if quote else close.iloc[-1]
    prev_close = close.iloc[-2] if len(close) >= 2 else current_price

    # ========== 1. 趋势信号（权重20%）==========
    try:
        trend = calc_trend(close)
        trend_score = trend["trend_score"]
        if trend_score >= 75:
            buy_signals.append(f"{trend['trend']}")
            buy_score += 15
        elif trend_score <= 35:
            sell_signals.append(f"{trend['trend']}")
            sell_score += 15
        elif trend_score >= 60:
            buy_score += 5
        elif trend_score <= 40:
            sell_score += 5
    except Exception:
        pass

    # ========== 2. MACD 信号（权重15%）==========
    try:
        macd = calc_macd(close)
        if macd.get("golden_cross"):
            buy_signals.append("MACD金叉")
            buy_score += 18
        elif macd.get("death_cross"):
            sell_signals.append("MACD死叉")
            sell_score += 18
        elif macd.get("dif", 0) > macd.get("dea", 0) and macd.get("dif", 0) > 0:
            buy_signals.append("MACD多头")
            buy_score += 6
        elif macd.get("dif", 0) < macd.get("dea", 0) and macd.get("dif", 0) < 0:
            sell_signals.append("MACD空头")
            sell_score += 6
        # MACD柱递增
        if macd.get("hist_increasing") and macd.get("dif", 0) > 0:
            buy_score += 4
    except Exception:
        pass

    # ========== 3. KDJ 信号（权重12%）==========
    try:
        kdj = calc_kdj(high, low, close)
        k_val = kdj.get("k", 50)
        if kdj.get("golden_cross") and k_val < 30:
            buy_signals.append(f"KDJ超卖金叉(K={k_val:.0f})")
            buy_score += 18
        elif kdj.get("golden_cross"):
            buy_signals.append("KDJ金叉")
            buy_score += 10
        elif kdj.get("death_cross") and k_val > 70:
            sell_signals.append(f"KDJ超买死叉(K={k_val:.0f})")
            sell_score += 18
        elif kdj.get("death_cross"):
            sell_signals.append("KDJ死叉")
            sell_score += 10
        # J值超卖
        if kdj.get("j_oversold"):
            buy_signals.append("J值超卖")
            buy_score += 6
    except Exception:
        pass

    # ========== 4. RSI 信号（权重10%）==========
    try:
        rsi6 = calc_rsi(close, 6)
        rsi14 = calc_rsi(close, 14)
        if pd.isna(rsi6):
            rsi6 = 50
        if rsi6 < 20:
            buy_signals.append(f"RSI6严重超卖({rsi6:.0f})")
            buy_score += 15
        elif rsi6 < 30:
            buy_signals.append(f"RSI6超卖({rsi6:.0f})")
            buy_score += 8
        elif rsi6 > 85:
            sell_signals.append(f"RSI6严重超买({rsi6:.0f})")
            sell_score += 15
        elif rsi6 > 75:
            sell_signals.append(f"RSI6超买({rsi6:.0f})")
            sell_score += 8
    except Exception:
        pass

    # ========== 5. 均线系统信号（权重12%）==========
    try:
        ma_sys = calc_ma_system(close)
        if ma_sys.get("bullish_alignment"):
            buy_signals.append("均线多头排列")
            buy_score += 12
        elif ma_sys.get("bearish_alignment"):
            sell_signals.append("均线空头排列")
            sell_score += 12
        # 价格在60日均线之上
        if ma_sys.get("price_above_ma60"):
            buy_score += 4
        else:
            sell_score += 4
        # MA5上穿MA10
        ma5 = calc_sma(close, 5)
        ma10 = calc_sma(close, 10)
        if ma5.iloc[-1] > ma10.iloc[-1] and ma5.iloc[-2] <= ma10.iloc[-2]:
            buy_signals.append("MA5上穿MA10")
            buy_score += 8
        elif ma5.iloc[-1] < ma10.iloc[-1] and ma5.iloc[-2] >= ma10.iloc[-2]:
            sell_signals.append("MA5下穿MA10")
            sell_score += 8
    except Exception:
        pass

    # ========== 6. 成交量信号（权重10%）==========
    try:
        vol = calc_volume_analysis(volume, close)
        vol_ratio = vol["volume_ratio"]
        vp = vol.get("volume_price", "")
        if "放量上涨" in vp:
            buy_signals.append(f"放量上涨(量比{vol_ratio:.1f})")
            buy_score += 12
        elif "放量下跌" in vp:
            sell_signals.append(f"放量下跌(量比{vol_ratio:.1f})")
            sell_score += 12
        elif "缩量下跌" in vp:
            buy_signals.append("缩量下跌(抛压减轻)")
            buy_score += 5
    except Exception:
        pass

    # ========== 7. 布林带信号（权重8%）==========
    boll_upper = None
    boll_lower = None
    boll_mid = None
    try:
        boll = calc_bollinger(close, 20, 2)
        boll_upper = boll.get("upper")
        boll_lower = boll.get("lower")
        boll_mid = boll.get("mid")
        if current_price <= boll_lower:
            buy_signals.append("触及布林下轨(超卖)")
            buy_score += 10
        elif current_price >= boll_upper:
            sell_signals.append("触及布林上轨(超买)")
            sell_score += 10
        # 布林带开口扩张+价格在上轨
        if boll.get("bandwidth_expanding") and current_price > boll_mid:
            buy_score += 4
    except Exception:
        pass

    # ========== 8. OBV 信号（权重5%）==========
    try:
        obv = calc_obv(close, volume)
        if obv.get("trend_up") and current_price < close.iloc[-5] if len(close) >= 5 else False:
            buy_signals.append("OBV底背离")
            buy_score += 10
        elif not obv.get("trend_up") and current_price > close.iloc[-5] if len(close) >= 5 else False:
            sell_signals.append("OBV顶背离")
            sell_score += 10
    except Exception:
        pass

    # ========== 9. Williams %R 信号（权重3%）==========
    try:
        wr = calc_williams_r(high, low, close)
        if wr.get("oversold"):
            buy_signals.append("Williams超卖")
            buy_score += 5
        elif wr.get("overbought"):
            sell_signals.append("Williams超买")
            sell_score += 5
    except Exception:
        pass

    # ========== 10. 动量信号（权重5%）==========
    try:
        mom = calc_momentum(close)
        roc5 = mom.get("roc5")
        if roc5 and roc5 > 5:
            buy_signals.append(f"短期动量强劲(+{roc5:.1f}%)")
            buy_score += 6
        elif roc5 and roc5 < -5:
            sell_signals.append(f"短期动量衰弱({roc5:.1f}%)")
            sell_score += 6
    except Exception:
        pass

    # ========== 市场环境过滤 ==========
    # 大盘弱势时，降低买入信号置信度，增强卖出信号
    market_adjustment = 0
    if market_sentiment_score < 40:
        market_adjustment = -8  # 大盘弱势，买入信号减分
        sell_score += 5
    elif market_sentiment_score > 65:
        market_adjustment = 5  # 大盘强势，买入信号加分
        buy_score += 3

    # ========== 综合判断 ==========
    net_score = buy_score - sell_score
    confidence = min(100, abs(net_score) + abs(market_adjustment))

    # 信号阈值（需要至少2个信号确认）
    if net_score >= 25 and len(buy_signals) >= 2:
        signal = "buy"
        action = "建议买入"
    elif net_score <= -25 and len(sell_signals) >= 2:
        signal = "sell"
        action = "建议卖出"
    elif net_score >= 12:
        signal = "hold_buy"
        action = "持有/可逢低买入"
    elif net_score <= -12:
        signal = "hold_sell"
        action = "持有/可逢高减仓"
    else:
        signal = "hold"
        action = "持有观望"

    # ========== 买卖点位计算（增强版）==========
    # 支撑压力位
    support_1 = None
    support_2 = None
    resistance_1 = None
    resistance_2 = None
    try:
        sr = calc_support_resistance(high, low, close, 60)
        support_1 = sr.get("support_1")
        support_2 = sr.get("support_2")
        resistance_1 = sr.get("resistance_1")
        resistance_2 = sr.get("resistance_2")
    except Exception:
        pass

    # ATR 用于动态止损
    atr_value = None
    try:
        atr = calc_atr(high, low, close)
        atr_value = atr.get("atr")
    except Exception:
        pass

    # 买入参考价：第一支撑位 或 布林带下轨（取较高者，更接近现价）
    buy_candidates = [s for s in [support_1, boll_lower] if s and s > 0]
    buy_price = max(buy_candidates) if buy_candidates else None

    # 如果当前价已经接近买入参考价（差距<2%），建议现价买入
    if buy_price and current_price > 0:
        gap = (buy_price - current_price) / current_price * 100
        if abs(gap) < 2:
            buy_price = current_price
            buy_price_note = "现价附近"
        elif gap > 0:
            buy_price_note = f"回调{gap:.1f}%"
        else:
            buy_price_note = "已跌破支撑"
    else:
        buy_price_note = ""

    # 卖出参考价：第一压力位 或 布林带上轨（取较低者，更接近现价）
    sell_candidates = [r for r in [resistance_1, boll_upper] if r and r > 0]
    sell_price = min(sell_candidates) if sell_candidates else None

    if sell_price and current_price > 0:
        gap = (sell_price - current_price) / current_price * 100
        if abs(gap) < 2:
            sell_price = current_price
            sell_price_note = "现价附近"
        elif gap > 0:
            sell_price_note = f"反弹{gap:.1f}%"
        else:
            sell_price_note = "已突破压力"
    else:
        sell_price_note = ""

    # 止损价：ATR动态止损 或 第二支撑位 或 第一支撑位下方3%
    stop_candidates = []
    if atr_value and current_price > 0:
        stop_candidates.append(current_price - 2 * atr_value)  # 2倍ATR止损
    if support_2:
        stop_candidates.append(support_2)
    if support_1:
        stop_candidates.append(support_1 * 0.97)
    stop_loss = min([s for s in stop_candidates if s and s > 0]) if stop_candidates else None

    # 目标价：第二压力位 或 第一压力位 或 当前价上方8%
    target_candidates = [r for r in [resistance_2, resistance_1] if r and r > 0]
    target_price = max(target_candidates) if target_candidates else None
    if not target_price and current_price > 0:
        target_price = current_price * 1.08

    # 盈亏比
    risk_reward_ratio = None
    if buy_price and target_price and stop_loss and buy_price > stop_loss:
        potential_gain = target_price - buy_price
        potential_loss = buy_price - stop_loss
        if potential_loss > 0:
            risk_reward_ratio = round(potential_gain / potential_loss, 2)

    return {
        "signal": signal,
        "action": action,
        "confidence": confidence,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "net_score": net_score,
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "price": current_price,
        "market_adjustment": market_adjustment,
        # 买卖点位
        "buy_price": round(buy_price, 2) if buy_price else None,
        "buy_price_note": buy_price_note,
        "sell_price": round(sell_price, 2) if sell_price else None,
        "sell_price_note": sell_price_note,
        "stop_loss": round(stop_loss, 2) if stop_loss else None,
        "target_price": round(target_price, 2) if target_price else None,
        "risk_reward_ratio": risk_reward_ratio,
        "atr": round(atr_value, 2) if atr_value else None,
        "support_1": round(support_1, 2) if support_1 else None,
        "support_2": round(support_2, 2) if support_2 else None,
        "resistance_1": round(resistance_1, 2) if resistance_1 else None,
        "resistance_2": round(resistance_2, 2) if resistance_2 else None,
    }


def batch_generate_signals(stocks_data: List[Dict], market_sentiment_score: int = 50) -> List[Dict]:
    """
    批量生成交易信号
    stocks_data: [{code, name, kline, quote}, ...]
    """
    results = []
    for data in stocks_data:
        try:
            signal = generate_trading_signal(data.get("kline"), data.get("quote"),
                                              market_sentiment_score)
            signal["code"] = data.get("code")
            signal["name"] = data.get("name")
            results.append(signal)
        except Exception as e:
            results.append({
                "code": data.get("code"),
                "name": data.get("name"),
                "signal": "hold",
                "action": "数据异常",
                "confidence": 0,
                "error": str(e),
            })
    return results


def get_buy_recommendations(signals: List[Dict], min_confidence: int = 40) -> List[Dict]:
    """获取买入推荐列表"""
    buys = [s for s in signals if s.get("signal") in ("buy", "hold_buy")
            and s.get("confidence", 0) >= min_confidence]
    buys.sort(key=lambda x: (x["confidence"], x["net_score"]), reverse=True)
    return buys


def get_sell_recommendations(signals: List[Dict], min_confidence: int = 40) -> List[Dict]:
    """获取卖出建议列表"""
    sells = [s for s in signals if s.get("signal") in ("sell", "hold_sell")
             and s.get("confidence", 0) >= min_confidence]
    sells.sort(key=lambda x: (x["confidence"], -x["net_score"]), reverse=True)
    return sells
