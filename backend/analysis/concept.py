"""
概念热点分析
"""
import logging
from typing import Dict, Any, List
from backend.data.collector import collector

logger = logging.getLogger(__name__)

# 全局缓存：热门概念数据只获取一次，避免重复调用API
_hot_concepts_cache = None
_hot_concepts_cache_time = None

def _get_cached_hot_concepts(top_n: int = 30):
    """获取缓存的热门概念数据，避免重复调用API"""
    global _hot_concepts_cache, _hot_concepts_cache_time
    import time
    current_time = time.time()
    
    # 缓存有效期5分钟
    if _hot_concepts_cache is not None and _hot_concepts_cache_time is not None:
        if current_time - _hot_concepts_cache_time < 300:
            return _hot_concepts_cache
    
    try:
        # 增加超时控制，避免长时间等待
        import signal
        def timeout_handler(signum, frame):
            raise TimeoutError("get_hot_concepts timeout")
        try:
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(10)  # 10秒超时
            df = collector.get_hot_concepts(top_n=top_n)
            signal.alarm(0)  # 取消超时
        except TimeoutError:
            signal.alarm(0)
            logger.warning("获取热门概念超时，使用空数据")
            df = None
        except Exception:
            signal.alarm(0)
            df = None
        
        _hot_concepts_cache = df
        _hot_concepts_cache_time = current_time
        return df
    except Exception as e:
        logger.warning(f"获取热门概念失败: {e}")
        return None


def analyze_concept(code: str) -> Dict[str, Any]:
    """概念热点分析入口（优化：增加缓存和快速失败机制）"""
    # 获取单只股票的概念数据（已经在collector中增加了3秒超时）
    concepts = collector.get_stock_concepts(code)
    
    # 获取缓存的热门概念数据
    hot_concepts = _get_cached_hot_concepts(top_n=30)

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
    df = _get_cached_hot_concepts(top_n=top_n)
    if df is None or df.empty:
        return []
    return df.to_dict(orient="records")
