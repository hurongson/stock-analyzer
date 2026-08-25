"""
选股引擎：调度五大策略，合并去重，综合排序
"""
import logging
from typing import List, Dict, Optional
import pandas as pd
from backend.data.collector import collector
from backend.config import Config
from backend.screener.strategies.low_price import LowPriceStrategy
from backend.screener.strategies.technical_pattern import TechnicalPatternStrategy
from backend.screener.strategies.capital_flow import CapitalFlowStrategy
from backend.screener.strategies.fundamental import FundamentalStrategy
from backend.screener.strategies.concept_hotspot import ConceptHotspotStrategy
from backend.utils.helpers import now_str

logger = logging.getLogger(__name__)


class ScreenerEngine:
    """选股引擎"""

    def __init__(self):
        self.strategies = {
            "low_price": LowPriceStrategy(),
            "technical_pattern": TechnicalPatternStrategy(),
            "capital_flow": CapitalFlowStrategy(),
            "fundamental": FundamentalStrategy(),
            "concept_hotspot": ConceptHotspotStrategy(),
        }

    def run_all(self, stock_df: Optional[pd.DataFrame] = None) -> Dict:
        """
        运行全部策略
        返回：{strategy_name: [results], "combined": [merged_results], "summary": {...}}
        """
        logger.info("开始运行选股引擎...")

        # 获取全量股票列表
        if stock_df is None:
            stock_df = collector.get_all_stocks()
        if stock_df is None or stock_df.empty:
            logger.error("无法获取股票列表")
            return {"error": "无法获取股票列表"}

        logger.info(f"股票池数量: {len(stock_df)}")

        all_results = {}
        for name, strategy in self.strategies.items():
            logger.info(f"运行策略: {strategy.name} - {strategy.description}")
            try:
                results = strategy.screen(stock_df)
                all_results[name] = results
                logger.info(f"  策略 {name} 选出 {len(results)} 只")
            except Exception as e:
                logger.error(f"策略 {name} 运行失败: {e}")
                all_results[name] = []

        # 合并去重 + 综合排序
        combined = self._merge_results(all_results)

        # 统计
        summary = {
            "run_time": now_str(),
            "total_stocks": len(stock_df),
            "strategy_counts": {k: len(v) for k, v in all_results.items()},
            "combined_count": len(combined),
        }

        logger.info(f"选股完成，合并后共 {len(combined)} 只股票")

        return {
            "strategies": all_results,
            "combined": combined,
            "summary": summary,
        }

    def _merge_results(self, all_results: Dict[str, List[Dict]]) -> List[Dict]:
        """合并各策略结果，去重，多策略命中加分"""
        stock_map = {}

        for strategy_name, results in all_results.items():
            for r in results:
                code = r["code"]
                if code not in stock_map:
                    stock_map[code] = {
                        "code": code,
                        "name": r["name"],
                        "price": r["price"],
                        "pct_change": r["pct_change"],
                        "strategies": [],
                        "reasons": [],
                        "total_score": 0,
                        "strategy_count": 0,
                    }
                stock_map[code]["strategies"].append(strategy_name)
                stock_map[code]["reasons"].append(f"[{strategy_name}] {r['reason']}")
                stock_map[code]["total_score"] += r["score"]
                stock_map[code]["strategy_count"] += 1

        # 多策略命中额外加分
        combined = list(stock_map.values())
        for item in combined:
            if item["strategy_count"] >= 3:
                item["total_score"] += 40  # 三策略共振（大幅加分）
                item["resonance"] = True
            elif item["strategy_count"] == 2:
                item["total_score"] += 20  # 双策略共振
                item["resonance"] = False
            else:
                item["resonance"] = False
            item["avg_score"] = round(item["total_score"] / item["strategy_count"], 1)

        combined.sort(key=lambda x: (x["strategy_count"], x["total_score"]), reverse=True)
        return combined[:Config.SCREENER_MAX_RESULTS]

    def run_single(self, strategy_name: str, stock_df: Optional[pd.DataFrame] = None) -> List[Dict]:
        """运行单个策略"""
        if strategy_name not in self.strategies:
            raise ValueError(f"未知策略: {strategy_name}，可选: {list(self.strategies.keys())}")
        if stock_df is None:
            stock_df = collector.get_all_stocks()
        return self.strategies[strategy_name].screen(stock_df)


# 全局单例
screener = ScreenerEngine()
