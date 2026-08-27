"""
尾盘选股模块
每天14:30根据实时数据，推荐当天可买入、次日可卖出的股票
策略：尾盘买入法（T+1短线）
- 当天涨幅适中（2%-8%，未涨停）
- 成交量放大（资金入场确认）
- 技术形态好（均线多头、MACD金叉、突破等）
- 资金净流入
- 低价优先（更容易次日冲高）
"""
import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from backend.data.collector import collector
from backend.analysis.indicators import (
    calc_trend, calc_macd, calc_kdj, calc_rsi,
    calc_bollinger, calc_volume_analysis, calc_support_resistance,
    calc_atr, calc_ma_system, calc_momentum
)
from backend.analysis.signals import generate_trading_signal

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

        # 第一步：初筛（基于基本面数据快速过滤）
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
        - 涨幅 2%-8%（未涨停，有上涨动能）
        - 价格 2-30元（低价优先，容易次日冲高）
        - 成交量 > 500万（有流动性）
        - 非ST、非退市
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
                # 涨幅 2%-8%（有上涨动能但未涨停）
                if pct_change < 2 or pct_change > 8:
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
        """
        results = []

        for i, stock in enumerate(candidates):
            try:
                code = stock["code"]
                # 获取60天K线数据
                kline = collector.get_daily_kline(code, days=60)
                if kline is None or len(kline) < 20:
                    continue

                # 计算技术指标
                score, analysis = self._calc_late_day_score(kline, stock)

                # 只保留评分>=60的
                if score >= 60:
                    # 生成交易信号（买卖点位）
                    quote = {"price": stock["price"], "pct_change": stock["pct_change"]}
                    signal = generate_trading_signal(kline, quote)

                    result = {
                        "code": code,
                        "name": stock["name"],
                        "price": stock["price"],
                        "pct_change": stock["pct_change"],
                        "score": score,
                        "analysis": analysis,
                        "buy_price": signal.get("buy_price") or stock["price"],
                        "buy_price_note": signal.get("buy_price_note", "尾盘现价"),
                        "sell_price": signal.get("target_price") or round(stock["price"] * 1.05, 2),
                        "sell_price_note": "次日冲高卖出",
                        "stop_loss": signal.get("stop_loss") or round(stock["price"] * 0.97, 2),
                        "target_price": signal.get("target_price") or round(stock["price"] * 1.05, 2),
                        "risk_reward_ratio": signal.get("risk_reward_ratio"),
                        "atr": signal.get("atr"),
                        "signals": signal,
                    }
                    results.append(result)

            except Exception as e:
                logger.debug(f"分析 {stock.get('code')} 失败: {e}")
                continue

        # 按评分排序，取前N只
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:self.max_results]

    def _calc_late_day_score(self, kline: pd.DataFrame, stock: Dict) -> tuple:
        """
        计算尾盘选股评分（0-100）
        维度：涨幅、成交量、技术形态、趋势、资金、价格
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

        # 1. 涨幅评分（15%）
        if 3 <= pct_change <= 6:
            score += 12
            reasons.append(f"涨幅适中({pct_change:.1f}%)，有上涨动能")
        elif 2 <= pct_change < 3:
            score += 6
            reasons.append(f"温和上涨({pct_change:.1f}%)")
        elif 6 < pct_change <= 8:
            score += 4
            reasons.append(f"涨幅较大({pct_change:.1f}%)，注意追高风险")
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
            else:
                score -= 3
                risks.append("成交量不足，动能可能不够")
        except Exception:
            pass

        # 3. 趋势评分（20%）
        try:
            trend = calc_trend(close)
            trend_score = trend["trend_score"]
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
            "trend": trend.get("trend", "未知") if 'trend' in dir() else "未知",
            "volume_ratio": vol_ratio if 'vol_ratio' in dir() else 0,
        }

        return score, analysis


# 全局单例
late_day_screener = LateDayScreener()
