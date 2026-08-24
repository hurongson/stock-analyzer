"""
策略五：概念热点选股
热门概念板块中的领涨股 + 概念叠加 + 资金认可
"""
import pandas as pd
from typing import List, Dict
from backend.screener.strategies.base import BaseStrategy
from backend.data.collector import collector

logger = __import__("logging").getLogger(__name__)


class ConceptHotspotStrategy(BaseStrategy):
    name = "concept_hotspot"
    description = "概念热点选股：热门概念领涨股+概念叠加+资金认可"

    def screen(self, df: pd.DataFrame, **kwargs) -> List[Dict]:
        results = []

        # 获取热门概念
        hot_concepts = collector.get_hot_concepts(top_n=15)
        if hot_concepts is None or hot_concepts.empty:
            logger.warning("无法获取热门概念数据")
            return results

        # 从涨幅榜中筛选（热门概念股通常涨幅靠前）
        candidates = df[
            (df["price"] > 2) &
            (df["price"] < 80) &
            (df["pct_change"] > 1) &
            (df["pct_change"] < 9.5) &
            (df["amount"] > 1e8) &
            (df["turnover"] > 2)
        ].copy()

        candidates = candidates.sort_values("pct_change", ascending=False).head(80)

        for _, row in candidates.iterrows():
            code = row["code"]
            try:
                concepts = collector.get_stock_concepts(code)
                if not concepts:
                    continue

                score = 40
                reasons = []
                matched = []

                # 匹配热门概念
                hot_names = hot_concepts["name"].tolist()
                for c in concepts:
                    if c in hot_names:
                        hot_row = hot_concepts[hot_concepts["name"] == c]
                        if not hot_row.empty:
                            pct = hot_row.iloc[0].get("pct_change", 0)
                            matched.append({"name": c, "pct": pct})
                            if pct > 4:
                                score += 18
                                reasons.append(f"「{c}」今日+{pct:.1f}%（风口）")
                            elif pct > 2:
                                score += 12
                                reasons.append(f"「{c}」今日+{pct:.1f}%（热门）")
                            else:
                                score += 6
                                reasons.append(f"「{c}」概念")

                # 概念叠加（多概念命中）
                if len(matched) >= 3:
                    score += 15
                    reasons.append(f"叠加{len(matched)}个热门概念")
                elif len(matched) >= 2:
                    score += 8
                    reasons.append(f"叠加{len(matched)}个热门概念")

                # 涨幅适中（不是最高，有空间）
                if 2 < row["pct_change"] < 7:
                    score += 8
                    reasons.append(f"今日+{row['pct_change']:.1f}%（仍有空间）")

                # 资金认可
                if row["turnover"] > 5:
                    score += 5
                    reasons.append(f"换手率{row['turnover']:.1f}%（资金活跃）")

                if matched and score >= 55:
                    results.append(self._make_result(
                        row,
                        "；".join(reasons),
                        min(100, score)
                    ))
            except Exception as e:
                logger.debug(f"概念分析 {code} 失败: {e}")
                continue

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:20]
