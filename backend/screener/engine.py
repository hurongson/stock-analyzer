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
from backend.analysis.signals import generate_trading_signal
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
        combined, special_picks = self._merge_results(all_results)

        # 统计
        summary = {
            "run_time": now_str(),
            "total_stocks": len(stock_df),
            "strategy_counts": {k: len(v) for k, v in all_results.items()},
            "combined_count": len(combined),
            "special_picks_count": len(special_picks),
        }

        logger.info(f"选股完成，合并后共 {len(combined)} 只股票，特别推荐 {len(special_picks)} 只")

        return {
            "strategies": all_results,
            "combined": combined,
            "special_picks": special_picks,
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
        combined = combined[:Config.SCREENER_MAX_RESULTS]

        # 为综合选股结果生成交易信号（买卖点位）+ 强势度评估
        logger.info(f"为 {len(combined)} 只选股生成交易信号和强势度评估...")
        for item in combined:
            try:
                kline = collector.get_daily_kline(item["code"], days=60)
                quote = {"price": item["price"], "pct_change": item["pct_change"]}
                signal = generate_trading_signal(kline, quote)
                item["trading_signal"] = signal

                # 强势度评估：近期涨幅、成交量放大、连续上涨、涨停
                strength_score = 0
                strength_reasons = []
                if kline is not None and len(kline) >= 5:
                    close = kline["close"]
                    volume = kline["volume"]
                    # 近3天涨幅
                    if len(close) >= 4:
                        pct_3d = (close.iloc[-1] - close.iloc[-4]) / close.iloc[-4] * 100
                        if pct_3d > 15:
                            strength_score += 25
                            strength_reasons.append(f"近3日大涨{pct_3d:.0f}%")
                        elif pct_3d > 8:
                            strength_score += 15
                            strength_reasons.append(f"近3日上涨{pct_3d:.0f}%")
                        elif pct_3d > 3:
                            strength_score += 5
                            strength_reasons.append(f"近3日温和上涨{pct_3d:.0f}%")
                    # 近5天是否有涨停
                    if len(kline) >= 5 and "pct_change" in kline.columns:
                        recent_5 = kline.tail(5)
                        if any(recent_5["pct_change"] > 9.5):
                            strength_score += 20
                            strength_reasons.append("近5日有涨停")
                    # 成交量放大
                    if len(volume) >= 6:
                        vol_ma5 = volume.tail(6).head(5).mean()
                        vol_today = volume.iloc[-1]
                        if vol_ma5 > 0:
                            vol_ratio = vol_today / vol_ma5
                            if vol_ratio > 2:
                                strength_score += 15
                                strength_reasons.append(f"成交量放大{vol_ratio:.1f}倍")
                            elif vol_ratio > 1.5:
                                strength_score += 8
                                strength_reasons.append(f"成交量温和放大{vol_ratio:.1f}倍")
                    # 连续上涨天数
                    if len(close) >= 4:
                        up_days = 0
                        for i in range(1, min(4, len(close))):
                            if close.iloc[-i] > close.iloc[-i-1]:
                                up_days += 1
                            else:
                                break
                        if up_days >= 3:
                            strength_score += 10
                            strength_reasons.append(f"连续{up_days}日上涨")
                item["strength_score"] = strength_score
                item["strength_reasons"] = strength_reasons
            except Exception as e:
                logger.debug(f"生成 {item['code']} 交易信号失败: {e}")
                item["trading_signal"] = None
                item["strength_score"] = 0
                item["strength_reasons"] = []

        # 特别推荐：综合评分 + 强势度 + 共振，精选3-5只
        special_picks = self._select_special_picks(combined)

        return combined, special_picks

    def _select_special_picks(self, combined: List[Dict]) -> List[Dict]:
        """
        特别推荐筛选：综合评分 + 强势度 + 共振 + 买入点位合理，精选3-5只
        """
        if not combined:
            return []

        scored = []
        for item in combined:
            # 综合评分（0-100）
            total_score = item.get("total_score", 0)
            # 强势度评分（0-100）
            strength_score = item.get("strength_score", 0)
            # 共振加分
            resonance_bonus = 30 if item.get("resonance") else 0
            # 策略数量加分
            strategy_bonus = item.get("strategy_count", 0) * 5

            # 买入点位合理性：当前价不要比买入价高太多（避免追高）
            ts = item.get("trading_signal") or {}
            buy_price = ts.get("buy_price")
            current_price = item.get("price", 0)
            position_score = 50
            if buy_price and current_price > 0:
                gap = (current_price - buy_price) / buy_price * 100
                if gap < 2:
                    position_score = 80  # 接近买入价，好
                elif gap < 5:
                    position_score = 60
                elif gap < 10:
                    position_score = 40
                else:
                    position_score = 20  # 已经涨太多，不适合追

            # 综合特别推荐评分
            special_score = (
                total_score * 0.3 +
                strength_score * 0.3 +
                resonance_bonus +
                strategy_bonus +
                position_score * 0.2
            )

            # 生成选中原因
            reasons = []
            if item.get("resonance"):
                reasons.append(f"{item['strategy_count']}策略共振")
            if strength_score >= 20:
                reasons.extend(item.get("strength_reasons", [])[:2])
            if total_score >= 70:
                reasons.append(f"综合评分{total_score:.0f}")
            if buy_price:
                reasons.append(f"买入参考{buy_price}元")

            item["special_score"] = round(special_score, 1)
            item["special_reasons"] = reasons
            scored.append(item)

        # 按特别推荐评分排序，取前5只
        scored.sort(key=lambda x: x["special_score"], reverse=True)
        return scored[:5]

    def run_single(self, strategy_name: str, stock_df: Optional[pd.DataFrame] = None) -> List[Dict]:
        """运行单个策略"""
        if strategy_name not in self.strategies:
            raise ValueError(f"未知策略: {strategy_name}，可选: {list(self.strategies.keys())}")
        if stock_df is None:
            stock_df = collector.get_all_stocks()
        return self.strategies[strategy_name].screen(stock_df)


# 全局单例
screener = ScreenerEngine()
