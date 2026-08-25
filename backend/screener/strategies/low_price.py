"""
策略一：低价潜力股
筛选条件：低价 + 小市值 + 基本面尚可 + 技术面企稳 + 量能放大
"""
import pandas as pd
from typing import List, Dict
from backend.screener.strategies.base import BaseStrategy
from backend.config import Config
from backend.data.collector import collector
from backend.analysis.indicators import calc_sma


class LowPriceStrategy(BaseStrategy):
    name = "low_price"
    description = "低价潜力股：低价+小市值+基本面尚可+技术企稳+量能放大"

    def screen(self, df: pd.DataFrame, **kwargs) -> List[Dict]:
        price_threshold = kwargs.get("price_threshold", Config.LOW_PRICE_THRESHOLD)
        results = []

        has_turnover = df["turnover"].max() > 0
        has_pe = df["pe"].max() > 0
        has_mv = df["total_mv"].max() > 0

        filtered = df[
            (df["price"] > 0) &
            (df["price"] <= price_threshold) &
            (df["pct_change"].abs() < 9.5) &
            (df["amount"] > 3e7)
        ].copy()

        if has_turnover:
            filtered = filtered[filtered["turnover"] > 0.3]
        if has_mv:
            filtered = filtered[filtered["total_mv"] < 300e8]
        if has_pe:
            filtered = filtered[(filtered["pe"] > 0) & (filtered["pe"] < 100)]

        filtered = filtered.head(100)

        for _, row in filtered.iterrows():
            code = row["code"]
            score = 50
            reasons = []

            if row["price"] < 3:
                score += 25
                reasons.append(f"股价{row['price']:.1f}元（超低价）")
            elif row["price"] < 5:
                score += 18
                reasons.append(f"股价{row['price']:.1f}元（低价）")
            elif row["price"] < 10:
                score += 10
                reasons.append(f"股价{row['price']:.1f}元（中低价）")
            else:
                score += 3
                reasons.append(f"股价{row['price']:.1f}元")

            mv_yi = row["total_mv"] / 1e8
            if has_mv and mv_yi > 0:
                if mv_yi < 30:
                    score += 18
                    reasons.append(f"市值{mv_yi:.0f}亿（微盘）")
                elif mv_yi < 80:
                    score += 12
                    reasons.append(f"市值{mv_yi:.0f}亿（小盘）")
                elif mv_yi < 150:
                    score += 6
                    reasons.append(f"市值{mv_yi:.0f}亿（中小盘）")

            if has_turnover and row["turnover"] > 0:
                if 1 < row["turnover"] < 10:
                    score += 8
                    reasons.append(f"换手率{row['turnover']:.1f}%（活跃）")
                elif row["turnover"] >= 10:
                    score += 4
                    reasons.append(f"换手率{row['turnover']:.1f}%（高换手）")

            if has_pe and row.get("pe") and 0 < row["pe"] < 40:
                score += 7
                reasons.append(f"PE{row['pe']:.1f}（估值合理）")

            if -3 < row["pct_change"] < 6:
                score += 5
                reasons.append(f"今日{row['pct_change']:+.1f}%（走势稳健）")
            elif row["pct_change"] >= 6:
                score -= 5
                reasons.append(f"今日{row['pct_change']:+.1f}%（短期涨幅较大）")

            try:
                kline = collector.get_daily_kline(code, days=30)
                if kline is not None and len(kline) >= 20:
                    close = kline["close"]
                    volume = kline["volume"]
                    ma5 = calc_sma(close, 5)
                    ma10 = calc_sma(close, 10)
                    ma20 = calc_sma(close, 20)
                    if ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1]:
                        score += 12
                        reasons.append("均线多头排列")
                    elif ma5.iloc[-1] > ma10.iloc[-1]:
                        score += 5
                        reasons.append("短期均线向上")

                    vol_ma5 = calc_sma(volume, 5)
                    if vol_ma5.iloc[-1] > 0:
                        vol_ratio = volume.iloc[-1] / vol_ma5.iloc[-1]
                        if vol_ratio > 1.5:
                            score += 8
                            reasons.append(f"量能放大（量比{vol_ratio:.1f}）")
                        elif vol_ratio > 1.2:
                            score += 4
                            reasons.append(f"量能温和放大（量比{vol_ratio:.1f}）")
            except Exception:
                pass

            results.append(self._make_result(row, "；".join(reasons), min(100, max(0, score))))

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:20]
