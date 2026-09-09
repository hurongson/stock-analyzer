"""
策略四：基本面选股
低估值 + 高ROE + 业绩增长 + 合理市值
"""
import time
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

        # 超时保护：基本面策略最多运行10分钟，避免获取财务数据超时导致整体超时
        start_time = time.time()
        MAX_RUN_TIME = 10 * 60  # 10分钟

        # 判断数据可用性
        has_pe = df["pe"].max() > 0
        has_pb = df["pb"].max() > 0
        has_mv = df["total_mv"].max() > 0

        # 初筛：基于可用数据过滤
        candidates = df[(df["price"] > 0) & (df["amount"] > 5e7)].copy()
        # 增加换手率过滤（优化：确保推荐股票有足够活跃度）
        if "turnover" in df.columns and df["turnover"].max() > 0:
            candidates = candidates[candidates["turnover"] > 1]  # 换手率>1%，确保活跃度
        if has_pe:
            candidates = candidates[(candidates["pe"] > 0) & (candidates["pe"] < 60)]
        if has_pb:
            candidates = candidates[(candidates["pb"] > 0) & (candidates["pb"] < 10)]
        if has_mv:
            candidates = candidates[(candidates["total_mv"] > 30e8) & (candidates["total_mv"] < 2000e8)]

        # 优化：从100只减少到30只，避免逐个获取财务数据导致运行超时
        candidates = candidates.sort_values("amount", ascending=False).head(30)

        logger.info(f"基本面策略候选股票: {len(candidates)}只（优化：从100只减少到30只，避免运行超时）")

        for _, row in candidates.iterrows():
            # 超时检查：如果超过10分钟，停止获取财务数据，使用已有数据
            if time.time() - start_time > MAX_RUN_TIME:
                logger.warning(f"基本面策略运行超过{MAX_RUN_TIME/60:.0f}分钟，停止获取财务数据，使用已有数据完成剩余股票")
                # 对剩余股票使用PE/PB简化判断
                fund = {"pe": row.get("pe"), "pb": row.get("pb")}
            else:
                code = row["code"]
                try:
                    fund = collector.get_fundamental(code)
                    if not fund:
                        # 用行情中的 PE/PB 做简化判断
                        fund = {"pe": row.get("pe"), "pb": row.get("pb")}
                except Exception as e:
                    logger.debug(f"基本面分析 {code} 失败: {e}")
                    # 失败时使用PE/PB简化判断，不重试
                    fund = {"pe": row.get("pe"), "pb": row.get("pb")}

            try:
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
                logger.debug(f"基本面分析 {row.get('code', '')} 评分失败: {e}")
                continue

        elapsed = time.time() - start_time
        logger.info(f"基本面策略完成: 选出{len(results)}只，运行时间{elapsed/60:.1f}分钟")
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:20]
