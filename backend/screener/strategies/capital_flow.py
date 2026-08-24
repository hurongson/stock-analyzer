"""
策略三：资金面选股
主力资金持续流入 + 大单净流入 + 量价配合
"""
import pandas as pd
from typing import List, Dict
from backend.screener.strategies.base import BaseStrategy
from backend.data.collector import collector

logger = __import__("logging").getLogger(__name__)


class CapitalFlowStrategy(BaseStrategy):
    name = "capital_flow"
    description = "资金面选股：主力资金持续流入+大单净流入+量价配合"

    def screen(self, df: pd.DataFrame, **kwargs) -> List[Dict]:
        results = []

        # 初筛：有一定成交额和涨幅
        candidates = df[
            (df["price"] > 2) &
            (df["price"] < 100) &
            (df["amount"] > 2e8) &  # 成交额大于2亿
            (df["pct_change"] > -3) &
            (df["pct_change"] < 9) &
            (df["turnover"] > 1)
        ].copy()

        candidates = candidates.head(80)

        for _, row in candidates.iterrows():
            code = row["code"]
            try:
                flow = collector.get_capital_flow(code)
                if not flow:
                    continue

                score = 40
                reasons = []

                main_net = flow.get("main_net_inflow", 0)
                main_pct = flow.get("main_net_pct", 0)
                main_5d = flow.get("main_net_inflow_5d", 0)
                super_large = flow.get("super_large_net", 0)

                # 当日主力流入
                if main_pct > 15:
                    score += 25
                    reasons.append(f"主力净流入占比{main_pct:.1f}%（大幅流入）")
                elif main_pct > 8:
                    score += 18
                    reasons.append(f"主力净流入占比{main_pct:.1f}%（明显流入）")
                elif main_pct > 3:
                    score += 10
                    reasons.append(f"主力净流入占比{main_pct:.1f}%")
                elif main_pct > 0:
                    score += 3
                    reasons.append(f"主力小幅净流入")
                else:
                    continue  # 主力流出直接跳过

                # 超大单流入
                if super_large > 0:
                    score += 10
                    reasons.append(f"超大单净流入{super_large/1e4:.0f}万")

                # 5日持续流入
                if main_5d and main_5d > 0:
                    if main_5d > main_net * 3:
                        score += 15
                        reasons.append(f"近5日持续净流入{main_5d/1e4:.0f}万")
                    else:
                        score += 8
                        reasons.append(f"近5日累计净流入{main_5d/1e4:.0f}万")

                # 量价配合：上涨+放量+资金流入
                if row["pct_change"] > 1 and row["turnover"] > 3:
                    score += 8
                    reasons.append("量价配合良好")

                if reasons:
                    results.append(self._make_result(
                        row,
                        "；".join(reasons),
                        min(100, score)
                    ))
            except Exception as e:
                logger.debug(f"资金面分析 {code} 失败: {e}")
                continue

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:20]
