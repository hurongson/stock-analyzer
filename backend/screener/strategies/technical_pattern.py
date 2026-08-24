"""
策略二：技术形态选股
包括：均线多头、放量突破、MACD金叉、KDJ超卖反弹、平台突破
"""
import pandas as pd
import numpy as np
from typing import List, Dict
from backend.screener.strategies.base import BaseStrategy
from backend.data.collector import collector
from backend.analysis.indicators import calc_sma, calc_macd, calc_kdj, calc_ema

logger = __import__("logging").getLogger(__name__)


class TechnicalPatternStrategy(BaseStrategy):
    name = "technical_pattern"
    description = "技术形态选股：均线多头/放量突破/MACD金叉/KDJ超卖/平台突破"

    def screen(self, df: pd.DataFrame, **kwargs) -> List[Dict]:
        results = []
        # 先从全量股票中初筛（流动性过滤）
        candidates = df[
            (df["price"] > 2) &
            (df["price"] < 100) &
            (df["amount"] > 1e8) &  # 成交额大于1亿
            (df["pct_change"].abs() < 9.5) &
            (df["turnover"] > 1)
        ].copy()

        # 限制分析数量（避免请求过多）
        candidates = candidates.head(80)

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

                # 1. 均线多头排列
                ma5 = calc_sma(close, 5)
                ma10 = calc_sma(close, 10)
                ma20 = calc_sma(close, 20)
                if ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1]:
                    score += 20
                    patterns.append("均线多头排列")

                # 2. 放量突破
                vol_ma5 = calc_sma(volume, 5)
                vol_ratio = volume.iloc[-1] / vol_ma5.iloc[-1] if vol_ma5.iloc[-1] > 0 else 1
                recent_high_20 = high.tail(20).max()
                if vol_ratio > 1.5 and close.iloc[-1] >= recent_high_20 * 0.98:
                    score += 20
                    patterns.append(f"放量突破（量比{vol_ratio:.1f}）")

                # 3. MACD 金叉
                macd = calc_macd(close)
                if macd["golden_cross"]:
                    score += 15
                    patterns.append("MACD金叉")
                elif macd["dif"] > macd["dea"] and macd["dif"] > 0:
                    score += 8
                    patterns.append("MACD多头")

                # 4. KDJ 超卖金叉
                kdj = calc_kdj(high, low, close)
                if kdj["golden_cross"] and kdj["k"] < 30:
                    score += 15
                    patterns.append("KDJ超卖金叉")
                elif kdj["golden_cross"]:
                    score += 8
                    patterns.append("KDJ金叉")

                # 5. 平台突破（近20日振幅 < 15%，今日突破）
                recent_20 = kline.tail(20)
                if len(recent_20) >= 15:
                    platform_high = recent_20["high"].max()
                    platform_low = recent_20["low"].min()
                    amplitude = (platform_high - platform_low) / platform_low * 100
                    if amplitude < 15 and close.iloc[-1] > platform_high * 0.97:
                        score += 12
                        patterns.append("平台突破")

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
