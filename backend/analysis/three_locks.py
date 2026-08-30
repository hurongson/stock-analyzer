"""
三把锁分析模块（参照指南针软件三把锁功能）
通过趋势、股性、资金三个维度综合判断买卖信号
- 趋势锁：均线多头排列、上升趋势确认
- 股性锁：KDJ/MACD金叉、成交量活跃、有波动空间
- 资金锁：主力资金持续流入、3日多空资金翻红

三把锁全亮 = 强烈买入信号
三把锁全灭 = 卖出信号
"""
import logging
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List
from backend.analysis.indicators import (
    calc_ma_system, calc_macd, calc_kdj, calc_rsi,
    calc_volume_analysis, calc_trend, calc_momentum,
    calc_bollinger, calc_atr
)

logger = logging.getLogger(__name__)


class ThreeLocksAnalyzer:
    """三把锁分析器"""

    def __init__(self):
        pass

    def analyze(self, kline: pd.DataFrame, quote: Optional[Dict] = None,
                capital_flow: Optional[Dict] = None) -> Dict:
        """
        三把锁综合分析
        返回：{
            trend_lock: {locked: bool, score: int, reasons: [], details: {}},
            activity_lock: {locked: bool, score: int, reasons: [], details: {}},
            capital_lock: {locked: bool, score: int, reasons: [], details: {}},
            total_locked: int,  # 点亮的锁数量 0-3
            signal: "强烈买入" | "买入" | "观望" | "卖出" | "强烈卖出",
            signal_strength: int,  # 信号强度 0-100
            summary: str,
        }
        """
        if kline is None or len(kline) < 20:
            return self._empty_result("K线数据不足")

        close = kline["close"]
        high = kline["high"]
        low = kline["low"]
        volume = kline["volume"]
        current_price = quote.get("price", close.iloc[-1]) if quote else close.iloc[-1]

        # 计算各锁
        trend_lock = self._calc_trend_lock(close, high, low, current_price)
        activity_lock = self._calc_activity_lock(close, high, low, volume, current_price, quote)
        capital_lock = self._calc_capital_lock(close, volume, capital_flow)

        # 统计点亮的锁
        total_locked = sum([
            1 if trend_lock["locked"] else 0,
            1 if activity_lock["locked"] else 0,
            1 if capital_lock["locked"] else 0,
        ])

        # 综合信号判断
        avg_score = (trend_lock["score"] + activity_lock["score"] + capital_lock["score"]) / 3
        signal, signal_strength = self._judge_signal(total_locked, avg_score, trend_lock, activity_lock, capital_lock)

        # 摘要
        lock_names = []
        if trend_lock["locked"]:
            lock_names.append("趋势锁🔒")
        if activity_lock["locked"]:
            lock_names.append("股性锁🔒")
        if capital_lock["locked"]:
            lock_names.append("资金锁🔒")

        if total_locked == 3:
            summary = f"三把锁全亮（{'/'.join(lock_names)}），强烈买入信号"
        elif total_locked == 2:
            summary = f"两把锁点亮（{'/'.join(lock_names)}），买入信号"
        elif total_locked == 1:
            summary = f"一把锁点亮（{'/'.join(lock_names)}），观望为主"
        else:
            summary = "三把锁全灭，卖出/观望信号"

        return {
            "trend_lock": trend_lock,
            "activity_lock": activity_lock,
            "capital_lock": capital_lock,
            "total_locked": total_locked,
            "signal": signal,
            "signal_strength": signal_strength,
            "summary": summary,
        }

    def _calc_trend_lock(self, close: pd.Series, high: pd.Series, low: pd.Series,
                          current_price: float) -> Dict:
        """
        第一把锁：趋势锁
        条件：
        - 均线多头排列（MA5 > MA10 > MA20）
        - 股价在MA20和MA60之上
        - 上升趋势确认（趋势评分 >= 60）
        - 近期高点不断抬高（近5日高点 > 前5日高点）
        """
        score = 0
        reasons = []
        risks = []
        details = {}

        # 1. 均线系统（40分）
        try:
            ma = calc_ma_system(close)
            details["ma5"] = ma.get("ma5")
            details["ma10"] = ma.get("ma10")
            details["ma20"] = ma.get("ma20")
            details["ma60"] = ma.get("ma60")

            if ma.get("bullish_alignment"):
                score += 25
                reasons.append("均线多头排列（MA5>MA10>MA20）")
            elif ma.get("ma5") and ma.get("ma10") and ma["ma5"] > ma["ma10"]:
                score += 10
                reasons.append("短期均线向上（MA5>MA10）")
            else:
                risks.append("均线未形成多头排列")

            # 股价在均线之上
            if ma.get("price_above_ma20"):
                score += 10
                reasons.append("股价在MA20之上")
            else:
                risks.append("股价跌破MA20")

            if ma.get("price_above_ma60"):
                score += 5
                reasons.append("股价在MA60之上")
        except Exception as e:
            logger.debug(f"趋势锁-均线计算失败: {e}")

        # 2. 趋势方向（30分）
        try:
            trend = calc_trend(close)
            trend_score = trend.get("trend_score", 50)
            details["trend"] = trend.get("trend", "未知")
            details["trend_score"] = trend_score

            if trend_score >= 75:
                score += 25
                reasons.append(f"强势上升趋势（{trend.get('trend')}）")
            elif trend_score >= 60:
                score += 15
                reasons.append(f"上升趋势（{trend.get('trend')}）")
            elif trend_score <= 35:
                risks.append(f"下降趋势（{trend.get('trend')}）")
        except Exception as e:
            logger.debug(f"趋势锁-趋势计算失败: {e}")

        # 3. 高点抬高（20分）
        try:
            if len(high) >= 10:
                recent_high = high.iloc[-5:].max()
                prev_high = high.iloc[-10:-5].max()
                details["recent_high"] = round(recent_high, 2)
                details["prev_high"] = round(prev_high, 2)

                if recent_high > prev_high:
                    score += 15
                    reasons.append("近期高点不断抬高")
                elif recent_high < prev_high * 0.95:
                    risks.append("近期高点降低")
        except Exception as e:
            logger.debug(f"趋势锁-高点计算失败: {e}")

        # 4. 布林带位置（10分）
        try:
            boll = calc_bollinger(close)
            upper = boll.get("upper")
            lower = boll.get("lower")
            middle = boll.get("middle")

            if upper and lower and middle:
                details["boll_upper"] = round(upper, 2)
                details["boll_middle"] = round(middle, 2)
                details["boll_lower"] = round(lower, 2)

                if current_price > middle:
                    score += 5
                    reasons.append("股价在布林中轨之上")
                if current_price > upper * 0.98:
                    risks.append("股价接近布林上轨，可能回调")
        except Exception as e:
            logger.debug(f"趋势锁-布林带计算失败: {e}")

        score = max(0, min(100, round(score)))
        locked = score >= 55  # 趋势锁门槛55分

        return {
            "locked": locked,
            "score": score,
            "reasons": reasons,
            "risks": risks,
            "details": details,
            "name": "趋势锁",
            "icon": "📈",
        }

    def _calc_activity_lock(self, close: pd.Series, high: pd.Series, low: pd.Series,
                             volume: pd.Series, current_price: float,
                             quote: Optional[Dict] = None) -> Dict:
        """
        第二把锁：股性锁（信号锁）
        条件：
        - KDJ金叉或多头排列（K>D，且未超买）
        - MACD金叉或多头排列（DIF>DEA，DIF>0）
        - 成交量放大（量比 > 1.2）
        - 振幅适中（2%-8%）
        - 换手率适中（3%-15%）
        """
        score = 0
        reasons = []
        risks = []
        details = {}

        # 1. KDJ（25分）
        try:
            kdj = calc_kdj(high, low, close)
            k_val = kdj.get("k", 50)
            d_val = kdj.get("d", 50)
            j_val = kdj.get("j", 50)
            details["kdj_k"] = round(k_val, 1)
            details["kdj_d"] = round(d_val, 1)
            details["kdj_j"] = round(j_val, 1)

            if kdj.get("golden_cross"):
                score += 20
                reasons.append("KDJ金叉，短期动能转强")
            elif k_val > d_val and k_val < 80:
                score += 12
                reasons.append(f"KDJ多头排列（K={k_val:.1f}>D={d_val:.1f}）")
            elif k_val > 85:
                risks.append(f"KDJ超买（K={k_val:.1f}），短期可能回调")
            elif kdj.get("death_cross"):
                risks.append("KDJ死叉，短期动能转弱")
        except Exception as e:
            logger.debug(f"股性锁-KDJ计算失败: {e}")

        # 2. MACD（25分）
        try:
            macd = calc_macd(close)
            dif = macd.get("dif", 0)
            dea = macd.get("dea", 0)
            macd_hist = macd.get("macd", 0)
            details["macd_dif"] = round(dif, 3)
            details["macd_dea"] = round(dea, 3)
            details["macd_hist"] = round(macd_hist, 3)

            if macd.get("golden_cross"):
                score += 20
                reasons.append("MACD金叉，中期动能转强")
            elif dif > dea and dif > 0:
                score += 15
                reasons.append("MACD多头排列（DIF>DEA>0）")
            elif dif > dea:
                score += 8
                reasons.append("MACD金叉状态（DIF>DEA）")
            elif macd.get("death_cross"):
                risks.append("MACD死叉，中期动能转弱")
        except Exception as e:
            logger.debug(f"股性锁-MACD计算失败: {e}")

        # 3. 成交量（25分）
        try:
            vol = calc_volume_analysis(volume, close)
            vol_ratio = vol.get("volume_ratio", 1)
            vp = vol.get("volume_price", "")
            details["volume_ratio"] = round(vol_ratio, 2)
            details["volume_price"] = vp

            if "放量上涨" in vp:
                score += 20
                reasons.append(f"放量上涨（量比{vol_ratio:.1f}），资金入场")
            elif vol_ratio > 1.5:
                score += 12
                reasons.append(f"成交量放大（量比{vol_ratio:.1f}）")
            elif vol_ratio > 1.2:
                score += 6
                reasons.append(f"成交量温和放大（量比{vol_ratio:.1f}）")
            elif vol_ratio < 0.7:
                risks.append(f"成交量萎缩（量比{vol_ratio:.1f}），股性不活跃")
        except Exception as e:
            logger.debug(f"股性锁-成交量计算失败: {e}")

        # 4. 振幅和换手率（15分）
        try:
            if len(high) >= 1 and len(low) >= 1:
                today_high = high.iloc[-1]
                today_low = low.iloc[-1]
                if current_price > 0:
                    amplitude = (today_high - today_low) / current_price * 100
                    details["amplitude"] = round(amplitude, 2)

                    if 2 <= amplitude <= 8:
                        score += 8
                        reasons.append(f"振幅适中（{amplitude:.1f}%），股性活跃")
                    elif amplitude > 10:
                        risks.append(f"振幅过大（{amplitude:.1f}%），风险较高")
                    elif amplitude < 1:
                        risks.append(f"振幅过小（{amplitude:.1f}%），股性呆滞")
        except Exception as e:
            logger.debug(f"股性锁-振幅计算失败: {e}")

        # 换手率（如果有数据）
        if quote and quote.get("turnover"):
            turnover = float(quote.get("turnover", 0))
            details["turnover"] = turnover
            if 3 <= turnover <= 15:
                score += 7
                reasons.append(f"换手率适中（{turnover:.1f}%）")
            elif turnover > 20:
                risks.append(f"换手率过高（{turnover:.1f}%），可能出货")

        # 5. RSI（10分）
        try:
            rsi = calc_rsi(close)
            rsi6 = rsi.get("rsi6", 50)
            details["rsi6"] = round(rsi6, 1)

            if 40 <= rsi6 <= 70:
                score += 8
                reasons.append(f"RSI健康（{rsi6:.1f}）")
            elif rsi6 > 80:
                risks.append(f"RSI超买（{rsi6:.1f}）")
            elif rsi6 < 20:
                reasons.append(f"RSI超卖（{rsi6:.1f}），可能反弹")
        except Exception as e:
            logger.debug(f"股性锁-RSI计算失败: {e}")

        score = max(0, min(100, round(score)))
        locked = score >= 50  # 股性锁门槛50分（尾盘选股股票本身股性活跃）

        return {
            "locked": locked,
            "score": score,
            "reasons": reasons,
            "risks": risks,
            "details": details,
            "name": "股性锁",
            "icon": "⚡",
        }

    def _calc_capital_lock(self, close: pd.Series, volume: pd.Series,
                            capital_flow: Optional[Dict] = None) -> Dict:
        """
        第三把锁：资金锁
        条件：
        - 主力资金净流入
        - 近3日资金持续流入
        - 大单净流入占比高
        - 量价配合（价涨量增）
        - OBV上升
        """
        score = 0
        reasons = []
        risks = []
        details = {}

        # 1. 资金流向数据（40分）
        if capital_flow:
            try:
                # 当日主力净流入
                main_net_inflow = capital_flow.get("main_net_inflow", 0)
                details["main_net_inflow"] = main_net_inflow

                if main_net_inflow > 0:
                    score += 20
                    reasons.append(f"主力资金净流入（{main_net_inflow/10000:.0f}万）")
                elif main_net_inflow < 0:
                    risks.append(f"主力资金净流出（{abs(main_net_inflow)/10000:.0f}万）")

                # 近3日资金趋势
                recent_flow = capital_flow.get("recent_3d_net_inflow", 0)
                details["recent_3d_net_inflow"] = recent_flow
                if recent_flow > 0:
                    score += 15
                    reasons.append("近3日资金持续流入")
                elif recent_flow < 0:
                    risks.append("近3日资金持续流出")

                # 大单占比
                large_order_ratio = capital_flow.get("large_order_ratio", 0)
                details["large_order_ratio"] = large_order_ratio
                if large_order_ratio > 0.3:
                    score += 5
                    reasons.append(f"大单占比高（{large_order_ratio*100:.0f}%）")
            except Exception as e:
                logger.debug(f"资金锁-资金流向计算失败: {e}")

        # 2. 量价配合（30分）
        try:
            if len(close) >= 5 and len(volume) >= 5:
                # 近5日价涨量增
                price_change = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100
                vol_change = (volume.iloc[-5:].mean() - volume.iloc[-10:-5].mean()) / volume.iloc[-10:-5].mean() * 100 if len(volume) >= 10 else 0

                details["5d_price_change"] = round(price_change, 2)
                details["5d_vol_change"] = round(vol_change, 2)

                if price_change > 0 and vol_change > 0:
                    score += 20
                    reasons.append("量价配合（价涨量增）")
                elif price_change > 0 and vol_change < 0:
                    score += 8
                    reasons.append("价涨量缩，上涨动能可能不足")
                    risks.append("价涨量缩，需警惕")
                elif price_change < 0 and vol_change > 0:
                    risks.append("价跌量增，可能出货")
        except Exception as e:
            logger.debug(f"资金锁-量价配合计算失败: {e}")

        # 3. OBV能量潮（20分）
        try:
            obv = [0]
            for i in range(1, len(close)):
                if close.iloc[i] > close.iloc[i-1]:
                    obv.append(obv[-1] + volume.iloc[i])
                elif close.iloc[i] < close.iloc[i-1]:
                    obv.append(obv[-1] - volume.iloc[i])
                else:
                    obv.append(obv[-1])

            obv_series = pd.Series(obv)
            obv_ma5 = obv_series.rolling(5).mean()

            if len(obv_series) >= 10 and not pd.isna(obv_ma5.iloc[-1]):
                obv_trend = (obv_series.iloc[-1] - obv_ma5.iloc[-1]) / abs(obv_ma5.iloc[-1]) * 100 if obv_ma5.iloc[-1] != 0 else 0
                details["obv_trend"] = round(obv_trend, 2)

                if obv_trend > 5:
                    score += 15
                    reasons.append("OBV能量潮上升，资金持续流入")
                elif obv_trend < -5:
                    risks.append("OBV能量潮下降，资金持续流出")
                else:
                    score += 5
        except Exception as e:
            logger.debug(f"资金锁-OBV计算失败: {e}")

        # 4. 资金动量（10分）
        try:
            mom = calc_momentum(close)
            roc5 = mom.get("roc5", 0)
            details["roc5"] = round(roc5, 2) if roc5 else 0

            if roc5 and roc5 > 0:
                score += 8
                reasons.append(f"5日动量为正（+{roc5:.1f}%）")
            elif roc5 and roc5 < -5:
                risks.append(f"5日动量为负（{roc5:.1f}%）")
        except Exception as e:
            logger.debug(f"资金锁-动量计算失败: {e}")

        score = max(0, min(100, round(score)))
        locked = score >= 40  # 资金锁门槛40分（缺少资金流向数据时，量价配合已能说明问题）

        return {
            "locked": locked,
            "score": score,
            "reasons": reasons,
            "risks": risks,
            "details": details,
            "name": "资金锁",
            "icon": "💰",
        }

    def _judge_signal(self, total_locked: int, avg_score: float,
                       trend_lock: Dict, activity_lock: Dict,
                       capital_lock: Dict) -> tuple:
        """
        综合判断买卖信号
        返回：(signal, signal_strength)
        """
        # 基础信号
        if total_locked == 3:
            signal = "强烈买入"
            strength = 85 + min(15, int(avg_score / 10))
        elif total_locked == 2:
            if trend_lock["locked"] and capital_lock["locked"]:
                signal = "买入"
                strength = 70 + min(10, int(avg_score / 10))
            else:
                signal = "谨慎买入"
                strength = 55 + min(10, int(avg_score / 10))
        elif total_locked == 1:
            if trend_lock["locked"]:
                signal = "观望（趋势向好）"
                strength = 45
            else:
                signal = "观望"
                strength = 35 + int(avg_score / 10)
        else:
            # 三把锁全灭
            if avg_score < 30:
                signal = "强烈卖出"
                strength = 20
            else:
                signal = "卖出"
                strength = 30

        # 风险调整
        total_risks = len(trend_lock["risks"]) + len(activity_lock["risks"]) + len(capital_lock["risks"])
        if total_risks >= 4:
            strength = max(20, strength - 15)
            if "买入" in signal:
                signal = signal.replace("买入", "谨慎")

        strength = max(0, min(100, strength))
        return signal, strength

    def _empty_result(self, reason: str) -> Dict:
        """空结果"""
        return {
            "trend_lock": {"locked": False, "score": 0, "reasons": [], "risks": [reason], "details": {}, "name": "趋势锁", "icon": "📈"},
            "activity_lock": {"locked": False, "score": 0, "reasons": [], "risks": [reason], "details": {}, "name": "股性锁", "icon": "⚡"},
            "capital_lock": {"locked": False, "score": 0, "reasons": [], "risks": [reason], "details": {}, "name": "资金锁", "icon": "💰"},
            "total_locked": 0,
            "signal": "数据不足",
            "signal_strength": 0,
            "summary": reason,
        }


# 全局单例
three_locks_analyzer = ThreeLocksAnalyzer()
