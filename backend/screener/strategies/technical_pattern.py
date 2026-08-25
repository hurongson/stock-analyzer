"""
策略二：技术形态选股
包括：均线多头、放量突破、MACD金叉、KDJ超卖反弹、RSI超卖反弹、平台突破
"""
import pandas as pd
import numpy as np
from typing import List, Dict
from backend.screener.strategies.base import BaseStrategy
from backend.data.collector import collector
from backend.analysis.indicators import calc_sma, calc_macd, calc_kdj, calc_ema, calc_rsi

logger = __import__("logging").getLogger(__name__)


class TechnicalPatternStrategy(BaseStrategy):
    name = "technical_pattern"
    description = "技术形态选股：均线多头/放量突破/MACD金叉/KDJ超卖/RSI超卖/平台突破"

    def screen(self, df: pd.DataFrame, **kwargs) -> List[Dict]:
        results = []
        candidates = df[
            (df["price"] > 2) &
            (df["price"] < 100) &
            (df["amount"] > 5e7) &
            (df["pct_change"].abs() < 9.5)
        ].copy()

        if df["turnover"].max() > 0:
            candidates = candidates[candidates["turnover"] > 0.5]

        candidates = candidates.head(100)

        for _, row in candidates.iterrows():
            code = row["code"]
            try:
                kline = collector.get_daily_kline(code, days=60)
                if kline is None or len(kline) < 30:
                    continue

                close = kline["close"]
                high = kline["high"]
                low = kline["low"]
                volume = kline["volume"]

                score = 40
                patterns = []
                pattern_count = 0

                # 1. 均线多头排列
                ma5 = calc_sma(close, 5)
                ma10 = calc_sma(close, 10)
                ma20 = calc_sma(close, 20)
                if ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1]:
                    score += 18
                    patterns.append("均线多头排列")
                    pattern_count += 1
                elif ma5.iloc[-1] > ma10.iloc[-1]:
                    score += 6
                    patterns.append("短期均线向上")

                # 2. 放量突破
                vol_ma5 = calc_sma(volume, 5)
                vol_ratio = volume.iloc[-1] / vol_ma5.iloc[-1] if vol_ma5.iloc[-1] > 0 else 1
                recent_high_20 = high.tail(20).max()
                if vol_ratio > 1.5 and close.iloc[-1] >= recent_high_20 * 0.98:
                    score += 18
                    patterns.append(f"放量突破（量比{vol_ratio:.1f}）")
                    pattern_count += 1
                elif vol_ratio > 1.3:
                    score += 5
                    patterns.append(f"量能放大（量比{vol_ratio:.1f}）")

                # 3. MACD 金叉
                macd = calc_macd(close)
                if macd["golden_cross"]:
                    score += 15
                    patterns.append("MACD金叉")
                    pattern_count += 1
                elif macd["dif"] > macd["dea"] and macd["dif"] > 0:
                    score += 8
                    patterns.append("MACD多头")

                # 4. KDJ 超卖金叉
                kdj = calc_kdj(high, low, close)
                if kdj["golden_cross"] and kdj["k"] < 30:
                    score += 15
                    patterns.append("KDJ超卖金叉")
                    pattern_count += 1
                elif kdj["golden_cross"]:
                    score += 8
                    patterns.append("KDJ金叉")

                # 5. RSI 超卖反弹
                try:
                    rsi_val = calc_rsi(close, 14)
                    rsi_prev = calc_rsi(close.iloc[:-1], 14) if len(close) > 15 else 50
                    if pd.isna(rsi_val):
                        rsi_val = 50
                    if pd.isna(rsi_prev):
                        rsi_prev = 50
                    if rsi_val < 30 and rsi_val > rsi_prev:
                        score += 12
                        patterns.append(f"RSI超卖反弹（{rsi_val:.0f}）")
                        pattern_count += 1
                    elif 30 <= rsi_val < 50 and rsi_val > rsi_prev:
                        score += 5
                        patterns.append(f"RSI低位回升（{rsi_val:.0f}）")
                except Exception:
                    pass

                # 6. 平台突破
                recent_20 = kline.tail(20)
                if len(recent_20) >= 15:
                    platform_high = recent_20["high"].max()
                    platform_low = recent_20["low"].min()
                    amplitude = (platform_high - platform_low) / platform_low * 100
                    if amplitude < 15 and close.iloc[-1] > platform_high * 0.97:
                        score += 12
                        patterns.append("平台突破")
                        pattern_count += 1

                # 多形态共振加分
                if pattern_count >= 3:
                    score += 10
                    patterns.append(f"多形态共振（{pattern_count}种）")
                elif pattern_count == 2:
                    score += 5

                if patterns:
                    results.append(self._make_result(
                        row,
                        f"技术形态：{'、'.join(patterns)}",
                        min(100, score)
                    ))
            except Exception as e:
                logger.debug(f"技术形态分析 {code} 失败: {e}")
                continue

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:20]
