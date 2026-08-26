"""
交易信号分析模块
基于技术指标给出明确的买入/卖出/持有建议，以及置信度
"""
import pandas as pd
from typing import Dict, List, Optional
from backend.analysis.indicators import (
    calc_sma, calc_ema, calc_macd, calc_kdj, calc_rsi,
    calc_bollinger, calc_volume_analysis, calc_support_resistance
)


def generate_trading_signal(kline: pd.DataFrame, quote: Dict = None) -> Dict:
    """
    生成单只股票的交易信号
    返回: {signal: 'buy'/'sell'/'hold', confidence: 0-100, reasons: [], price: ...}
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

    # 当前价格（用最新收盘价，或实时报价）
    current_price = quote.get("price") if quote else close.iloc[-1]
    prev_close = close.iloc[-2] if len(close) >= 2 else current_price

    # ========== 1. MACD 信号 ==========
    try:
        macd = calc_macd(close)
        if macd.get("golden_cross"):
            buy_signals.append("MACD金叉")
            buy_score += 20
        elif macd.get("death_cross"):
            sell_signals.append("MACD死叉")
            sell_score += 20
        elif macd.get("dif", 0) > macd.get("dea", 0) and macd.get("dif", 0) > 0:
            buy_signals.append("MACD多头排列")
            buy_score += 8
        elif macd.get("dif", 0) < macd.get("dea", 0) and macd.get("dif", 0) < 0:
            sell_signals.append("MACD空头排列")
            sell_score += 8
    except Exception:
        pass

    # ========== 2. KDJ 信号 ==========
    try:
        kdj = calc_kdj(high, low, close)
        k_val = kdj.get("k", 50)
        d_val = kdj.get("d", 50)
        if kdj.get("golden_cross") and k_val < 30:
            buy_signals.append(f"KDJ超卖金叉(K={k_val:.0f})")
            buy_score += 20
        elif kdj.get("golden_cross"):
            buy_signals.append("KDJ金叉")
            buy_score += 10
        elif kdj.get("death_cross") and k_val > 70:
            sell_signals.append(f"KDJ超买死叉(K={k_val:.0f})")
            sell_score += 20
        elif kdj.get("death_cross"):
            sell_signals.append("KDJ死叉")
            sell_score += 10
    except Exception:
        pass

    # ========== 3. RSI 信号 ==========
    try:
        rsi = calc_rsi(close, 14)
        if pd.isna(rsi):
            rsi = 50
        if rsi < 25:
            buy_signals.append(f"RSI严重超卖({rsi:.0f})")
            buy_score += 18
        elif rsi < 35:
            buy_signals.append(f"RSI超卖({rsi:.0f})")
            buy_score += 10
        elif rsi > 80:
            sell_signals.append(f"RSI严重超买({rsi:.0f})")
            sell_score += 18
        elif rsi > 70:
            sell_signals.append(f"RSI超买({rsi:.0f})")
            sell_score += 10
    except Exception:
        pass

    # ========== 4. 均线信号 ==========
    try:
        ma5 = calc_sma(close, 5)
        ma10 = calc_sma(close, 10)
        ma20 = calc_sma(close, 20)
        ma60 = calc_sma(close, 60) if len(close) >= 60 else ma20

        # 均线多头排列
        if ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1]:
            buy_signals.append("均线多头排列(5>10>20)")
            buy_score += 15
        # 均线空头排列
        elif ma5.iloc[-1] < ma10.iloc[-1] < ma20.iloc[-1]:
            sell_signals.append("均线空头排列(5<10<20)")
            sell_score += 15

        # 价格突破20日均线
        if current_price > ma20.iloc[-1] and prev_close <= ma20.iloc[-2]:
            buy_signals.append("突破20日均线")
            buy_score += 12
        elif current_price < ma20.iloc[-1] and prev_close >= ma20.iloc[-2]:
            sell_signals.append("跌破20日均线")
            sell_score += 12

        # 价格在60日均线之上（中期趋势向上）
        if current_price > ma60.iloc[-1]:
            buy_score += 5
        else:
            sell_score += 5
    except Exception:
        pass

    # ========== 5. 成交量信号 ==========
    try:
        vol_ma5 = calc_sma(volume, 5)
        if vol_ma5.iloc[-1] > 0:
            vol_ratio = volume.iloc[-1] / vol_ma5.iloc[-1]
            price_change = (current_price - prev_close) / prev_close * 100 if prev_close else 0

            # 放量上涨（买入信号）
            if vol_ratio > 1.5 and price_change > 0:
                buy_signals.append(f"放量上涨(量比{vol_ratio:.1f})")
                buy_score += 12
            # 放量下跌（卖出信号）
            elif vol_ratio > 1.5 and price_change < 0:
                sell_signals.append(f"放量下跌(量比{vol_ratio:.1f})")
                sell_score += 12
            # 缩量下跌（可能止跌）
            elif vol_ratio < 0.7 and price_change < 0:
                buy_signals.append("缩量下跌(可能止跌)")
                buy_score += 5
    except Exception:
        pass

    # ========== 6. 布林带信号 ==========
    boll_upper = None
    boll_lower = None
    boll_mid = None
    try:
        boll = calc_bollinger(close, 20, 2)
        boll_upper = boll.get("upper")
        boll_lower = boll.get("lower")
        boll_mid = boll.get("mid")
        if isinstance(boll_upper, pd.Series):
            boll_upper = boll_upper.iloc[-1]
        if isinstance(boll_lower, pd.Series):
            boll_lower = boll_lower.iloc[-1]
        if isinstance(boll_mid, pd.Series):
            boll_mid = boll_mid.iloc[-1]
        if current_price <= boll_lower:
            buy_signals.append("触及布林带下轨(超卖)")
            buy_score += 10
        elif current_price >= boll_upper:
            sell_signals.append("触及布林带上轨(超买)")
            sell_score += 10
    except Exception:
        pass

    # ========== 7. 支撑压力位 ==========
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

    # ========== 综合判断 ==========
    net_score = buy_score - sell_score
    confidence = min(100, abs(net_score))

    if net_score >= 25 and len(buy_signals) >= 2:
        signal = "buy"
        action = "建议买入"
    elif net_score <= -25 and len(sell_signals) >= 2:
        signal = "sell"
        action = "建议卖出"
    elif net_score >= 10:
        signal = "hold_buy"
        action = "持有/可逢低买入"
    elif net_score <= -10:
        signal = "hold_sell"
        action = "持有/可逢高减仓"
    else:
        signal = "hold"
        action = "持有观望"

    # ========== 买卖点位计算 ==========
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
    # 如果当前价已经接近卖出参考价（差距<2%），建议现价卖出
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

    # 止损价：第二支撑位 或 第一支撑位下方3%
    stop_candidates = [s for s in [support_2, support_1 * 0.97 if support_1 else None] if s and s > 0]
    stop_loss = min(stop_candidates) if stop_candidates else None

    # 目标价：第二压力位 或 第一压力位
    target_candidates = [r for r in [resistance_2, resistance_1] if r and r > 0]
    target_price = max(target_candidates) if target_candidates else None
    # 如果没有压力位，目标价设为当前价上方8%
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
        # 买卖点位
        "buy_price": round(buy_price, 2) if buy_price else None,
        "buy_price_note": buy_price_note,
        "sell_price": round(sell_price, 2) if sell_price else None,
        "sell_price_note": sell_price_note,
        "stop_loss": round(stop_loss, 2) if stop_loss else None,
        "target_price": round(target_price, 2) if target_price else None,
        "risk_reward_ratio": risk_reward_ratio,
        "support_1": round(support_1, 2) if support_1 else None,
        "support_2": round(support_2, 2) if support_2 else None,
        "resistance_1": round(resistance_1, 2) if resistance_1 else None,
        "resistance_2": round(resistance_2, 2) if resistance_2 else None,
    }


def batch_generate_signals(stocks_data: List[Dict]) -> List[Dict]:
    """
    批量生成交易信号
    stocks_data: [{code, name, kline, quote}, ...]
    """
    results = []
    for data in stocks_data:
        try:
            signal = generate_trading_signal(data.get("kline"), data.get("quote"))
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
