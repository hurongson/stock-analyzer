"""
资金面分析
"""
import logging
from typing import Dict, Any
from backend.data.collector import collector

logger = logging.getLogger(__name__)


def analyze_capital_flow(code: str) -> Dict[str, Any]:
    """资金面分析入口"""
    flow = collector.get_capital_flow(code)
    if not flow:
        return {"error": "无法获取资金流向数据", "score": 50, "conclusions": ["资金流向数据暂不可用"]}

    conclusions = []
    score = 50

    main_net = flow.get("main_net_inflow", 0)
    main_pct = flow.get("main_net_pct", 0)
    main_5d = flow.get("main_net_inflow_5d", 0)

    # 当日主力资金
    if main_net > 0:
        if main_pct > 10:
            conclusions.append(f"主力净流入{main_net/1e4:.0f}万（占比{main_pct:.1f}%，大幅流入）")
            score += 20
        elif main_pct > 5:
            conclusions.append(f"主力净流入{main_net/1e4:.0f}万（占比{main_pct:.1f}%，明显流入）")
            score += 12
        else:
            conclusions.append(f"主力净流入{main_net/1e4:.0f}万（占比{main_pct:.1f}%，小幅流入）")
            score += 5
    else:
        if main_pct < -10:
            conclusions.append(f"主力净流出{abs(main_net)/1e4:.0f}万（占比{main_pct:.1f}%，大幅流出）")
            score -= 20
        elif main_pct < -5:
            conclusions.append(f"主力净流出{abs(main_net)/1e4:.0f}万（占比{main_pct:.1f}%，明显流出）")
            score -= 12
        else:
            conclusions.append(f"主力净流出{abs(main_net)/1e4:.0f}万（占比{main_pct:.1f}%，小幅流出）")
            score -= 5

    # 5日主力资金趋势
    if main_5d is not None:
        if main_5d > 0:
            conclusions.append(f"近5日主力累计净流入{main_5d/1e4:.0f}万（资金持续关注）")
            score += 8
        else:
            conclusions.append(f"近5日主力累计净流出{abs(main_5d)/1e4:.0f}万（资金持续撤离）")
            score -= 8

    # 大单结构
    super_large = flow.get("super_large_net", 0)
    large = flow.get("large_net", 0)
    if super_large > 0 and large > 0:
        conclusions.append("超大单+大单双双流入，机构资金积极")
        score += 5
    elif super_large < 0 and large < 0:
        conclusions.append("超大单+大单双双流出，机构资金撤离")
        score -= 5

    score = max(0, min(100, score))
    return {
        "data": flow,
        "score": score,
        "conclusions": conclusions,
    }
