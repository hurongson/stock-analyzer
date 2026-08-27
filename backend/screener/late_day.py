"""
尾盘选股模块（优化版）
每天14:30根据实时数据，推荐当天可买入、次日可卖出的股票
策略：尾盘买入法（T+1短线）
参照公开尾盘选股策略优化：
- 买入价 = 尾盘现价（直接买入，不等回调）
- 卖出价 = 次日冲高3%-5%（止盈目标）
- 止损价 = 买入价下方2%-3%（固定比例止损）
- 选股条件：涨幅2%-6%、量比>1、股价在20日均线之上、非ST
"""
import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from backend.data.collector import collector
from backend.analysis.indicators import (
    calc_sma, calc_trend, calc_macd, calc_kdj, calc_rsi,
    calc_bollinger, calc_volume_analysis, calc_ma_system, calc_momentum
)

logger = logging.getLogger(__name__)


class LateDayScreener:
    """尾盘选股器"""

    def __init__(self):
        self.max_results = 8  # 最多推荐8只

    def screen(self, stock_df: Optional[pd.DataFrame] = None) -> Dict:
        """
        尾盘选股主函数
        返回：{picks: [...], summary: {...}}
        """
        logger.info("开始尾盘选股...")

        # 获取全量股票列表
        if stock_df is None:
            stock_df = collector.get_all_stocks()
        if stock_df is None or stock_df.empty:
            return {"error": "无法获取股票列表", "picks": []}

        logger.info(f"股票池数量: {len(stock_df)}")

        # 第一步：初筛（基于实时行情数据快速过滤）
        candidates = self._initial_filter(stock_df)
        logger.info(f"初筛后剩余: {len(candidates)} 只")

        if not candidates:
            return {"picks": [], "summary": {"total": 0, "filtered": 0}}

        # 第二步：深度分析（获取K线数据，计算技术指标）
        picks = self._deep_analyze(candidates)
        logger.info(f"尾盘选股完成，共推荐 {len(picks)} 只")

        return {
            "picks": picks,
            "summary": {
                "total_stocks": len(stock_df),
                "initial_filtered": len(candidates),
                "final_picks": len(picks),
            }
        }

    def _initial_filter(self, stock_df: pd.DataFrame) -> List[Dict]:
        """
        初筛：基于实时行情数据快速过滤
        条件：
        - 涨幅 2%-6%（有上涨动能但未涨停，不过高）
        - 价格 2-30元（低价优先，容易次日冲高）
        - 成交量 > 500万（有流动性）
        - 非ST、非退市
        - 非北交所、非科创板
        """
        candidates = []
        for _, row in stock_df.iterrows():
            try:
                code = str(row.get("code", ""))
                name = str(row.get("name", ""))
                price = float(row.get("price", 0))
                pct_change = float(row.get("pct_change", 0))
                volume = float(row.get("volume", 0))

                # 过滤条件
                if price <= 0 or pct_change == 0:
                    continue
                # 涨幅 2%-6%（优化：降低上限，避免追高）
                if pct_change < 2 or pct_change > 6:
                    continue
                # 价格 2-30元
                if price < 2 or price > 30:
                    continue
                # 排除ST和退市
                if "ST" in name or "退" in name or "*" in name:
                    continue
                # 排除北交所（8开头）和科创板（688开头，波动大）
                if code.startswith("8") or code.startswith("4") or code.startswith("688"):
                    continue

                candidates.append({
                    "code": code,
                    "name": name,
                    "price": price,
                    "pct_change": pct_change,
                    "volume": volume,
                })
            except Exception:
                continue

        return candidates

    def _deep_analyze(self, candidates: List[Dict]) -> List[Dict]:
        """
        深度分析：获取K线数据，计算技术指标，评分排序
        买卖点位逻辑（参照公开尾盘买入法）：
        - 买入价 = 尾盘现价（14:30-15:00直接买入）
        - 卖出价 = 次日冲高3%（止盈目标，保守）
        - 目标价 = 次日冲高5%（激进目标）
        - 止损价 = 买入价下方2%（固定比例止损）
        """
        results = []

        for i, stock in enumerate(candidates):
            try:
                code = stock["code"]
                # 获取60天K线数据
                kline = collector.get_daily_kline(code, days=60)
                if kline is None or len(kline) < 20:
                    continue

                close = kline["close"]
                current_price = stock["price"]

                # 关键过滤：股价必须在20日均线之上（趋势向上）
                ma20 = calc_sma(close, 20).iloc[-1]
                if current_price < ma20:
                    continue

                # 计算技术指标
                score, analysis = self._calc_late_day_score(kline, stock)

                # 只保留评分>=60的
                if score >= 60:
                    # === 买卖点位计算（参照公开尾盘买入法）===
                    # 买入价 = 尾盘现价（直接买入，不等回调）
                    buy_price = round(current_price, 2)
                    buy_price_note = "尾盘现价买入"

                    # 卖出价 = 次日冲高3%（保守止盈）
                    target_3pct = round(current_price * 1.03, 2)
                    target_5pct = round(current_price * 1.05, 2)
                    sell_price = target_3pct
                    sell_price_note = "次日冲高3%止盈"
                    target_price = target_5pct

                    # 止损价 = 买入价下方2%（固定比例止损）
                    stop_loss = round(current_price * 0.98, 2)
                    stop_loss_note = "跌破2%止损"

                    # 盈亏比 = (目标价-买入价)/(买入价-止损价)
                    risk_reward_ratio = round((target_price - buy_price) / (buy_price - stop_loss), 2) if buy_price > stop_loss else None

                    # 次日卖出策略
                    sell_strategy = self._get_sell_strategy(buy_price, target_3pct, target_5pct, stop_loss)

                    result = {
                        "code": code,
                        "name": stock["name"],
                        "price": stock["price"],
                        "pct_change": stock["pct_change"],
                        "score": score,
                        "analysis": analysis,
                        "buy_price": buy_price,
                        "buy_price_note": buy_price_note,
                        "sell_price": sell_price,
                        "sell_price_note": sell_price_note,
                        "stop_loss": stop_loss,
                        "stop_loss_note": stop_loss_note,
                        "target_price": target_price,
                        "risk_reward_ratio": risk_reward_ratio,
                        "sell_strategy": sell_strategy,
                        "ma20": round(ma20, 2),
                    }
                    results.append(result)

            except Exception as e:
                logger.debug(f"分析 {stock.get('code')} 失败: {e}")
                continue

        # 按评分排序，取前N只
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:self.max_results]

    def _get_sell_strategy(self, buy_price: float, target_3pct: float, target_5pct: float, stop_loss: float) -> Dict:
        """
        次日卖出策略（参照公开尾盘买入法）
        """
        return {
            "time": "次日9:30-10:30（早盘半小时内必须卖出）",
            "take_profit_1": f"高开3%以上：开盘5分钟不涨停直接卖出（{target_3pct}元）",
            "take_profit_2": f"平开/小幅高开：冲高3%-5%分批卖出（{target_3pct}-{target_5pct}元）",
            "take_profit_3": "涨停封死：可持有到第三天，跌破分时线再卖",
            "stop_loss_1": f"低开：开盘15分钟内无法翻红，果断止损（{stop_loss}元）",
            "stop_loss_2": f"跌破昨日收盘价：立即卖出（{buy_price}元）",
            "stop_loss_3": f"亏损达到2%：无条件止损（{stop_loss}元）",
            "core_rule": "无论盈亏，次日10:30前必卖，绝不延长持仓",
        }

    def _calc_late_day_score(self, kline: pd.DataFrame, stock: Dict) -> tuple:
        """
        计算尾盘选股评分（0-100）
        维度：涨幅、成交量、趋势、MACD、KDJ、价格、动量、20日均线
        """
        close = kline["close"]
        high = kline["high"]
        low = kline["low"]
        volume = kline["volume"]
        current_price = stock["price"]
        pct_change = stock["pct_change"]

        score = 50  # 基准分
        reasons = []
        risks = []
        vol_ratio = 0
        trend_name = "未知"

        # 1. 涨幅评分（15%）
        if 3 <= pct_change <= 5:
            score += 12
            reasons.append(f"涨幅适中({pct_change:.1f}%)，有上涨动能")
        elif 2 <= pct_change < 3:
            score += 6
            reasons.append(f"温和上涨({pct_change:.1f}%)")
        elif 5 < pct_change <= 6:
            score += 4
            reasons.append(f"涨幅偏大({pct_change:.1f}%)，注意追高风险")
            risks.append("涨幅偏大，次日可能回调")

        # 2. 成交量评分（20%）
        try:
            vol = calc_volume_analysis(volume, close)
            vol_ratio = vol["volume_ratio"]
            vp = vol.get("volume_price", "")
            if "放量上涨" in vp:
                score += 18
                reasons.append(f"放量上涨(量比{vol_ratio:.1f})，资金入场")
            elif vol_ratio > 1.5:
                score += 10
                reasons.append(f"成交量放大(量比{vol_ratio:.1f})")
            elif vol_ratio > 1.2:
                score += 5
                reasons.append(f"成交量温和放大(量比{vol_ratio:.1f})")
            elif vol_ratio < 0.8:
                score -= 5
                risks.append("成交量不足，动能可能不够")
        except Exception:
            pass

        # 3. 趋势评分（20%）
        try:
            trend = calc_trend(close)
            trend_score = trend["trend_score"]
            trend_name = trend["trend"]
            if trend_score >= 75:
                score += 15
                reasons.append(f"{trend['trend']}，趋势向好")
            elif trend_score >= 60:
                score += 8
                reasons.append(f"{trend['trend']}")
            elif trend_score <= 35:
                score -= 10
                risks.append(f"{trend['trend']}，趋势偏弱")
        except Exception:
            pass

        # 4. MACD评分（15%）
        try:
            macd = calc_macd(close)
            if macd.get("golden_cross"):
                score += 12
                reasons.append("MACD金叉，短期动能转强")
            elif macd["dif"] > macd["dea"] and macd["dif"] > 0:
                score += 8
                reasons.append("MACD多头排列")
            elif macd.get("death_cross"):
                score -= 8
                risks.append("MACD死叉，短期动能转弱")
        except Exception:
            pass

        # 5. KDJ评分（10%）
        try:
            kdj = calc_kdj(high, low, close)
            k_val = kdj.get("k", 50)
            if kdj.get("golden_cross") and k_val < 50:
                score += 8
                reasons.append("KDJ金叉，低位启动")
            elif 30 <= k_val <= 70:
                score += 3
            elif k_val > 85:
                score -= 5
                risks.append("KDJ超买，次日可能回调")
        except Exception:
            pass

        # 6. 价格评分（10%）
        if current_price < 5:
            score += 8
            reasons.append(f"低价股({current_price}元)，容易次日冲高")
        elif current_price < 10:
            score += 5
            reasons.append(f"中低价股({current_price}元)")
        elif current_price > 20:
            score -= 3

        # 7. 动量评分（10%）
        try:
            mom = calc_momentum(close)
            roc5 = mom.get("roc5")
            if roc5 and 2 <= roc5 <= 10:
                score += 6
                reasons.append(f"5日动量适中(+{roc5:.1f}%)")
            elif roc5 and roc5 > 15:
                score -= 3
                risks.append("短期涨幅过大，可能回调")
        except Exception:
            pass

        score = max(0, min(100, round(score)))

        analysis = {
            "reasons": reasons,
            "risks": risks,
            "trend": trend_name,
            "volume_ratio": vol_ratio,
        }

        return score, analysis


# 全局单例
late_day_screener = LateDayScreener()
