"""
策略四：基本面选股
低估值 + 高ROE + 业绩增长 + 合理市值
"""
import pandas as pd
from typing import List, Dict
from backend.screener.strategies.base import BaseStrategy
from backend.data.collector import collector

logger = __import__("logging").getLogger(__name__)


class FundamentalStrategy(BaseStrategy):
    name = "fundamental"
    description = "基本面选股：低估值+高ROE+业绩增长+合理市值"

    def screen(self, df: pd.DataFrame, **kwargs) -> List[Dict]:
        results = []

        # 判断数据可用性
        has_pe = df["pe"].max() > 0
        has_pb = df["pb"].max() > 0
        has_mv = df["total_mv"].max() > 0

        # 初筛：基于可用数据过滤
        candidates = df[(df["price"] > 0) & (df["amount"] > 5e7)].copy()
        if has_pe:
            candidates = candidates[(candidates["pe"] > 0) & (candidates["pe"] < 60)]
        if has_pb:
            candidates = candidates[(candidates["pb"] > 0) & (candidates["pb"] < 10)]
        if has_mv:
            candidates = candidates[(candidates["total_mv"] > 30e8) & (candidates["total_mv"] < 2000e8)]

        candidates = candidates.head(100)

        for _, row in candidates.iterrows():
            code = row["code"]
            try:
                fund = collector.get_fundamental(code)
                if not fund:
                    # 用行情中的 PE/PB 做简化判断
                    fund = {"pe": row.get("pe"), "pb": row.get("pb")}

                score = 40
                reasons = []

                pe = fund.get("pe") or row.get("pe")
                pb = fund.get("pb") or row.get("pb")
                roe = fund.get("roe")
                rev_yoy = fund.get("revenue_yoy")
                profit_yoy = fund.get("profit_yoy")
                gross_margin = fund.get("gross_margin")

                # PE 估值
                if pe and 0 < pe < 15:
                    score += 18
                    reasons.append(f"PE={pe:.1f}（低估）")
                elif pe and pe < 30:
                    score += 10
                    reasons.append(f"PE={pe:.1f}（合理）")
                elif pe and pe < 50:
                    score += 3
                    reasons.append(f"PE={pe:.1f}（偏高）")

                # PB
                if pb and pb < 1.5:
                    score += 12
                    reasons.append(f"PB={pb:.2f}（低估值）")
                elif pb and pb < 3:
                    score += 6
                    reasons.append(f"PB={pb:.2f}（合理）")

                # ROE
                if roe:
                    if roe > 20:
                        score += 20
                        reasons.append(f"ROE={roe:.1f}%（优秀）")
                    elif roe > 12:
                        score += 12
                        reasons.append(f"ROE={roe:.1f}%（良好）")
                    elif roe > 8:
                        score += 5
                        reasons.append(f"ROE={roe:.1f}%（一般）")

                # 营收增长
                if rev_yoy is not None:
                    if rev_yoy > 30:
                        score += 12
                        reasons.append(f"营收+{rev_yoy:.1f}%（高增长）")
                    elif rev_yoy > 15:
                        score += 7
                        reasons.append(f"营收+{rev_yoy:.1f}%（稳健增长）")
                    elif rev_yoy > 0:
                        score += 2
                        reasons.append(f"营收+{rev_yoy:.1f}%")

                # 净利润增长
                if profit_yoy is not None:
                    if profit_yoy > 50:
                        score += 15
                        reasons.append(f"净利润+{profit_yoy:.1f}%（高增长）")
                    elif profit_yoy > 20:
                        score += 8
                        reasons.append(f"净利润+{profit_yoy:.1f}%（良好）")
                    elif profit_yoy > 0:
                        score += 3
                        reasons.append(f"净利润+{profit_yoy:.1f}%")

                # 毛利率
                if gross_margin and gross_margin > 40:
                    score += 5
                    reasons.append(f"毛利率{gross_margin:.1f}%（高毛利）")

                # 市值适中
                mv_yi = row["total_mv"] / 1e8
                if 50 < mv_yi < 300:
                    score += 5
                    reasons.append(f"市值{mv_yi:.0f}亿（适中）")

                if score >= 60:
                    results.append(self._make_result(
                        row,
                        "；".join(reasons) if reasons else "基本面尚可",
                        min(100, score)
                    ))
            except Exception as e:
                logger.debug(f"基本面分析 {code} 失败: {e}")
                continue

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:20]
