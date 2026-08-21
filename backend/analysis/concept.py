"""
概念热点分析
"""
import logging
from typing import Dict, Any, List
from backend.data.collector import collector

logger = logging.getLogger(__name__)


def analyze_concept(code: str) -> Dict[str, Any]:
    """概念热点分析入口"""
    concepts = collector.get_stock_concepts(code)
    hot_concepts = collector.get_hot_concepts(top_n=30)

    conclusions = []
    score = 50
    matched_hot = []

    if concepts and hot_concepts is not None and not hot_concepts.empty:
        hot_names = set(hot_concepts["name"].tolist())
        for c in concepts:
            if c in hot_names:
                row = hot_concepts[hot_concepts["name"] == c]
                if not row.empty:
                    pct = row.iloc[0].get("pct_change", 0)
                    matched_hot.append({"name": c, "pct_change": pct})
                    if pct > 3:
                        conclusions.append(f"所属概念「{c}」今日涨幅{pct:.1f}%（热门风口）")
                        score += 15
                    elif pct > 1:
                        conclusions.append(f"所属概念「{c}」今日涨幅{pct:.1f}%（活跃）")
                        score += 8
                    elif pct > 0:
                        conclusions.append(f"所属概念「{c}」今日微涨{pct:.1f}%")
                        score += 3
                    else:
                        conclusions.append(f"所属概念「{c}」今日下跌{pct:.1f}%")
                        score -= 3

    if concepts:
        conclusions.append(f"所属行业/概念：{'、'.join(concepts)}")
    else:
        conclusions.append("暂无明确概念标签")

    if not matched_hot and hot_concepts is not None and not hot_concepts.empty:
        top3 = hot_concepts.head(3)
        hot_list = "、".join([f"{r['name']}({r['pct_change']:.1f}%)" for _, r in top3.iterrows()])
        conclusions.append(f"当前市场热点：{hot_list}（该股非核心标的）")
        score -= 5

    score = max(0, min(100, score))
    return {
        "concepts": concepts or [],
        "matched_hot": matched_hot,
        "score": score,
        "conclusions": conclusions,
    }


def get_market_hotspots(top_n: int = 10) -> List[Dict]:
    """获取市场热门概念"""
    df = collector.get_hot_concepts(top_n=top_n)
    if df is None or df.empty:
        return []
    return df.to_dict(orient="records")
