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
from backend.analysis.three_locks import three_locks_analyzer
from backend.analysis.trend_analysis import trend_analyzer
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

        # 涨停预测
        limit_up_picks = self._predict_limit_up(combined)

        # 统计
        summary = {
            "run_time": now_str(),
            "total_stocks": len(stock_df),
            "strategy_counts": {k: len(v) for k, v in all_results.items()},
            "combined_count": len(combined),
            "special_picks_count": len(special_picks),
            "limit_up_picks_count": len(limit_up_picks),
        }

        logger.info(f"选股完成，合并后共 {len(combined)} 只股票，特别推荐 {len(special_picks)} 只，涨停预测 {len(limit_up_picks)} 只")

        return {
            "strategies": all_results,
            "combined": combined,
            "special_picks": special_picks,
            "limit_up_picks": limit_up_picks,
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

                # 三把锁分析（所有选股都带三把锁状态）
                try:
                    three_locks = three_locks_analyzer.analyze(kline, quote)
                    item["three_locks"] = three_locks
                except Exception as e:
                    logger.debug(f"生成 {item['code']} 三把锁失败: {e}")
                    item["three_locks"] = None

                # 走势分析
                try:
                    trend_analysis = trend_analyzer.analyze(kline, quote)
                    item["trend_analysis"] = trend_analysis
                except Exception as e:
                    logger.debug(f"生成 {item['code']} 走势分析失败: {e}")
                    item["trend_analysis"] = None

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

        # 按三把锁信号过滤：只保留买入/强烈买入信号的股票作为推荐
        buy_signals = ["强烈买入", "买入", "谨慎买入"]
        buy_combined = [c for c in combined if c.get("three_locks", {}).get("signal", "") in buy_signals]
        watch_combined = [c for c in combined if c.get("three_locks", {}).get("signal", "") not in buy_signals]
        
        logger.info(f"三把锁过滤: 买入信号{len(buy_combined)}只, 观望/卖出{len(watch_combined)}只")
        
        # 推荐列表只包含买入信号股票，观望股票单独保存供参考
        recommended_combined = buy_combined if buy_combined else combined[:10]

        # 特别推荐：综合评分 + 强势度 + 共振 + 三把锁全亮，精选3-5只
        special_picks = self._select_special_picks(recommended_combined)

        return recommended_combined, special_picks

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

            # 三把锁全亮加分（特别推荐必须优先三把锁全亮的股票）
            tl = item.get("three_locks", {})
            tl_locked = tl.get("total_locked", 0)
            tl_signal = tl.get("signal", "")
            tl_bonus = 40 if tl_locked == 3 else (20 if tl_locked == 2 else 0)
            
            # 非买入信号的股票不进入特别推荐
            if tl_signal not in ["强烈买入", "买入", "谨慎买入"]:
                continue

            # 综合特别推荐评分
            special_score = (
                total_score * 0.2 +
                strength_score * 0.2 +
                resonance_bonus +
                strategy_bonus +
                position_score * 0.2 +
                tl_bonus
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

    def _predict_limit_up(self, combined: List[Dict]) -> List[Dict]:
        """
        涨停预测：从选股结果中筛选未来1-3天最可能涨停的股票
        评分维度：技术突破、强势度、低价效应、成交量、均线多头
        """
        if not combined:
            return []

        predicted = []
        for item in combined:
            ts = item.get("trading_signal") or {}
            kline = None
            try:
                kline = collector.get_daily_kline(item["code"], days=60)
            except Exception:
                pass

            limit_up_score = 0
            reasons = []

            # 1. 低价效应（10元以下更容易涨停）
            price = item.get("price", 0)
            if price < 3:
                limit_up_score += 25
                reasons.append(f"超低价{price}元（易涨停）")
            elif price < 5:
                limit_up_score += 18
                reasons.append(f"低价{price}元")
            elif price < 10:
                limit_up_score += 10
                reasons.append(f"中低价{price}元")

            # 2. 强势度（近期上涨、成交量放大）
            strength_score = item.get("strength_score", 0)
            if strength_score >= 30:
                limit_up_score += 20
                reasons.extend(item.get("strength_reasons", [])[:2])
            elif strength_score >= 15:
                limit_up_score += 12
                reasons.extend(item.get("strength_reasons", [])[:1])

            # 3. 技术形态（突破、均线多头、MACD金叉）
            if kline is not None and len(kline) >= 20:
                close = kline["close"]
                # 突破近20日高点
                high_20 = close.tail(20).max()
                if close.iloc[-1] >= high_20 * 0.98:
                    limit_up_score += 15
                    reasons.append("逼近20日高点（突破在即）")

                # 均线多头排列
                if len(close) >= 10:
                    ma5 = close.tail(5).mean()
                    ma10 = close.tail(10).mean()
                    if ma5 > ma10 and close.iloc[-1] > ma5:
                        limit_up_score += 10
                        reasons.append("均线多头排列")

            # 4. 交易信号（买入信号）
            signal = ts.get("signal", "")
            if signal in ("buy", "hold_buy"):
                limit_up_score += 10
                reasons.append(f"技术信号: {ts.get('action', '买入')}")

            # 5. 多策略共振
            if item.get("resonance"):
                limit_up_score += 10
                reasons.append(f"{item['strategy_count']}策略共振")

            # 6. 综合评分高
            if item.get("avg_score", 0) >= 85:
                limit_up_score += 8
                reasons.append(f"综合评分{item['avg_score']}")

            item["limit_up_score"] = limit_up_score
            item["limit_up_reasons"] = reasons
            item["limit_up_probability"] = min(95, round(limit_up_score * 0.8, 0))  # 转换为概率百分比
            predicted.append(item)

        # 按涨停概率排序，取前5只
        predicted.sort(key=lambda x: x["limit_up_score"], reverse=True)
        return predicted[:5]

    def run_single(self, strategy_name: str, stock_df: Optional[pd.DataFrame] = None) -> List[Dict]:
        """运行单个策略"""
        if strategy_name not in self.strategies:
            raise ValueError(f"未知策略: {strategy_name}，可选: {list(self.strategies.keys())}")
        if stock_df is None:
            stock_df = collector.get_all_stocks()
        return self.strategies[strategy_name].screen(stock_df)


# 全局单例
screener = ScreenerEngine()
