"""
基本面分析
"""
import logging
from typing import Dict, Any
from backend.data.collector import collector

logger = logging.getLogger(__name__)


def analyze_fundamental(code: str) -> Dict[str, Any]:
    """基本面分析入口"""
    fund = collector.get_fundamental(code)
    if not fund:
        return {"error": "无法获取基本面数据", "score": 50, "conclusions": ["基本面数据暂不可用"]}

    conclusions = []
    score = 50

    # PE 估值
    pe = fund.get("pe")
    if pe is not None:
        if pe < 0:
            conclusions.append(f"PE={pe:.1f}（亏损）")
            score -= 15
        elif pe < 15:
            conclusions.append(f"PE={pe:.1f}（低估）")
            score += 15
        elif pe < 30:
            conclusions.append(f"PE={pe:.1f}（合理）")
            score += 5
        elif pe < 60:
            conclusions.append(f"PE={pe:.1f}（偏高）")
            score -= 5
        else:
            conclusions.append(f"PE={pe:.1f}（高估值）")
            score -= 10

    # PB
    pb = fund.get("pb")
    if pb is not None:
        if pb < 1:
            conclusions.append(f"PB={pb:.2f}（破净）")
            score += 10
        elif pb < 3:
            conclusions.append(f"PB={pb:.2f}（合理）")
            score += 3
        elif pb < 8:
            conclusions.append(f"PB={pb:.2f}（偏高）")
            score -= 3
        else:
            conclusions.append(f"PB={pb:.2f}（高估值）")
            score -= 8

    # ROE
    roe = fund.get("roe")
    if roe is not None:
        if roe > 20:
            conclusions.append(f"ROE={roe:.1f}%（优秀）")
            score += 15
        elif roe > 10:
            conclusions.append(f"ROE={roe:.1f}%（良好）")
            score += 8
        elif roe > 5:
            conclusions.append(f"ROE={roe:.1f}%（一般）")
            score += 0
        else:
            conclusions.append(f"ROE={roe:.1f}%（偏弱）")
            score -= 8

    # 营收增长
    rev_yoy = fund.get("revenue_yoy")
    if rev_yoy is not None:
        if rev_yoy > 30:
            conclusions.append(f"营收同比+{rev_yoy:.1f}%（高增长）")
            score += 12
        elif rev_yoy > 10:
            conclusions.append(f"营收同比+{rev_yoy:.1f}%（稳健增长）")
            score += 6
        elif rev_yoy > 0:
            conclusions.append(f"营收同比+{rev_yoy:.1f}%（微增）")
            score += 0
        else:
            conclusions.append(f"营收同比{rev_yoy:.1f}%（下滑）")
            score -= 10

    # 净利润增长
    profit_yoy = fund.get("profit_yoy")
    if profit_yoy is not None:
        if profit_yoy > 50:
            conclusions.append(f"净利润同比+{profit_yoy:.1f}%（高增长）")
            score += 12
        elif profit_yoy > 20:
            conclusions.append(f"净利润同比+{profit_yoy:.1f}%（良好增长）")
            score += 8
        elif profit_yoy > 0:
            conclusions.append(f"净利润同比+{profit_yoy:.1f}%（微增）")
            score += 0
        else:
            conclusions.append(f"净利润同比{profit_yoy:.1f}%（下滑）")
            score -= 12

    # 毛利率
    gm = fund.get("gross_margin")
    if gm is not None:
        if gm > 50:
            conclusions.append(f"毛利率{gm:.1f}%（高毛利）")
            score += 5
        elif gm > 25:
            conclusions.append(f"毛利率{gm:.1f}%（中等）")
            score += 2
        else:
            conclusions.append(f"毛利率{gm:.1f}%（偏低）")
            score -= 3

    # 市值
    mv = fund.get("total_mv")
    if mv:
        mv_yi = mv / 1e8
        if mv_yi < 50:
            conclusions.append(f"总市值{mv_yi:.0f}亿（小盘）")
        elif mv_yi < 200:
            conclusions.append(f"总市值{mv_yi:.0f}亿（中盘）")
        elif mv_yi < 1000:
            conclusions.append(f"总市值{mv_yi:.0f}亿（大盘）")
        else:
            conclusions.append(f"总市值{mv_yi:.0f}亿（超大盘）")

    score = max(0, min(100, score))
    return {
        "data": fund,
        "score": score,
        "conclusions": conclusions,
    }
