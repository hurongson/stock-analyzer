"""
策略一：低价潜力股
筛选条件：低价 + 小市值 + 基本面尚可 + 技术面企稳
"""
import pandas as pd
from typing import List, Dict
from backend.screener.strategies.base import BaseStrategy
from backend.config import Config


class LowPriceStrategy(BaseStrategy):
    name = "low_price"
    description = "低价潜力股：低价+小市值+基本面尚可+技术企稳"

    def screen(self, df: pd.DataFrame, **kwargs) -> List[Dict]:
        price_threshold = kwargs.get("price_threshold", Config.LOW_PRICE_THRESHOLD)
        results = []

        # 判断数据可用性（Tushare低积分时 turnover/pe/total_mv 可能为0）
        has_turnover = df["turnover"].max() > 0
        has_pe = df["pe"].max() > 0
        has_mv = df["total_mv"].max() > 0

        # 基础过滤
        filtered = df[
            (df["price"] > 0) &
            (df["price"] <= price_threshold) &
            (df["pct_change"].abs() < 9.5) &  # 排除涨跌停
            (df["amount"] > 5e7)  # 成交额大于5000万
        ].copy()

        # 换手率过滤（数据可用时）
        if has_turnover:
            filtered = filtered[filtered["turnover"] > 0.5]

        # 小市值优先（数据可用时）
        if has_mv:
            filtered = filtered[filtered["total_mv"] < 200e8]

        # PE 合理（数据可用时）
        if has_pe:
            filtered = filtered[(filtered["pe"] > 0) & (filtered["pe"] < 80)]

        # 评分：价格越低分越高，市值越小分越高，换手率适中加分
        for _, row in filtered.iterrows():
            score = 50
            reasons = []

            # 价格因子
            if row["price"] < 5:
                score += 20
                reasons.append(f"股价{row['price']:.1f}元（超低价）")
            elif row["price"] < 10:
                score += 12
                reasons.append(f"股价{row['price']:.1f}元（低价）")
            else:
                score += 5
                reasons.append(f"股价{row['price']:.1f}元")

            # 市值因子
            mv_yi = row["total_mv"] / 1e8
            if mv_yi < 50:
                score += 15
                reasons.append(f"市值{mv_yi:.0f}亿（小盘）")
            elif mv_yi < 100:
                score += 8
                reasons.append(f"市值{mv_yi:.0f}亿（中小盘）")

            # 换手率
            if 1 < row["turnover"] < 8:
                score += 8
                reasons.append(f"换手率{row['turnover']:.1f}%（活跃）")

            # PE
            if row.get("pe") and 0 < row["pe"] < 30:
                score += 7
                reasons.append(f"PE{row['pe']:.1f}（估值合理）")

            # 今日涨幅适中
            if -2 < row["pct_change"] < 5:
                score += 5
                reasons.append(f"今日{row['pct_change']:+.1f}%（走势稳健）")

            results.append(self._make_result(row, "；".join(reasons), min(100, score)))

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:20]
