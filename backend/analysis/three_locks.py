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
        第二把锁：股性锁（指南针官方规则：要活不要死）
        核心：股性活跃，有波动空间，不是KDJ/MACD金叉
        条件：
        - 振幅适中（3%-8%为最佳活跃区间）
        - 量比活跃（1.5-3倍为交投活跃）
        - 近期有大涨/涨停记录（20日内有大涨=股性活跃）
        - 量能趋势放大（5日均量>10日均量）
        """
        score = 0
        reasons = []
        risks = []
        details = {}

        # 1. 振幅分析（30分）- 波动空间是股性活跃的核心
        try:
            if len(high) >= 10 and len(low) >= 10:
                # 10日平均振幅
                amplitudes_10d = []
                for i in range(-10, 0):
                    if low.iloc[i] > 0:
                        amp = (high.iloc[i] - low.iloc[i]) / low.iloc[i] * 100
                        amplitudes_10d.append(amp)
                
                # 5日平均振幅
                amplitudes_5d = amplitudes_10d[-5:] if len(amplitudes_10d) >= 5 else amplitudes_10d
                
                if amplitudes_5d:
                    avg_amp_5d = sum(amplitudes_5d) / len(amplitudes_5d)
                    avg_amp_10d = sum(amplitudes_10d) / len(amplitudes_10d)
                    details["avg_amplitude_5d"] = round(avg_amp_5d, 2)
                    details["avg_amplitude_10d"] = round(avg_amp_10d, 2)
                    
                    # 5日振幅：3%-8%为最佳活跃区间
                    if 3 <= avg_amp_5d <= 8:
                        score += 25
                        reasons.append(f"5日振幅{avg_amp_5d:.1f}%，波动空间适中，股性活跃")
                    elif 2 <= avg_amp_5d < 3:
                        score += 15
                        reasons.append(f"5日振幅{avg_amp_5d:.1f}%，波动空间一般")
                    elif avg_amp_5d > 8:
                        score += 12
                        reasons.append(f"5日振幅{avg_amp_5d:.1f}%，波动剧烈")
                        risks.append("振幅过大，短线风险较高")
                    else:
                        risks.append(f"5日振幅{avg_amp_5d:.1f}%，股性不活跃，差价空间小")
                    
                    # 振幅递增（活跃度提升）
                    if avg_amp_5d > avg_amp_10d * 1.1:
                        score += 5
                        reasons.append("近期振幅放大，股性趋于活跃")
        except Exception as e:
            logger.debug(f"股性锁-振幅计算失败: {e}")

        # 2. 近期大涨/涨停记录（25分）- 股性活跃的重要标志
        try:
            if len(close) >= 20:
                # 计算20日内涨跌幅
                pct_changes_20d = []
                for i in range(-20, 0):
                    if i-1 >= -len(close):
                        pct = (close.iloc[i] - close.iloc[i-1]) / close.iloc[i-1] * 100
                        pct_changes_20d.append(pct)
                
                if pct_changes_20d:
                    big_yang_count = sum(1 for c in pct_changes_20d if c >= 5)
                    zhangting_count = sum(1 for c in pct_changes_20d if c >= 9.5)
                    details["big_yang_count_20d"] = big_yang_count
                    details["zhangting_count_20d"] = zhangting_count
                    
                    if zhangting_count >= 2:
                        score += 25
                        reasons.append(f"20日内{zhangting_count}次涨停，股性极其活跃")
                    elif zhangting_count == 1:
                        score += 18
                        reasons.append("20日内有1次涨停，股性活跃")
                    elif big_yang_count >= 3:
                        score += 15
                        reasons.append(f"20日内{big_yang_count}次大涨(>5%)，股性较活跃")
                    elif big_yang_count >= 1:
                        score += 8
                        reasons.append("20日内有大涨记录，股性一般")
                    else:
                        risks.append("20日内无大涨记录，股性呆滞")
        except Exception as e:
            logger.debug(f"股性锁-大涨记录计算失败: {e}")

        # 3. 量比活跃度（25分）- 交投活跃程度
        try:
            vol = calc_volume_analysis(volume, close)
            vol_ratio = vol.get("volume_ratio", 1)
            details["volume_ratio"] = round(vol_ratio, 2)
            
            # 量比：1.5-3倍为活跃
            if 1.5 <= vol_ratio <= 3:
                score += 20
                reasons.append(f"量比{vol_ratio:.1f}，交投活跃")
            elif 1.2 <= vol_ratio < 1.5:
                score += 12
                reasons.append(f"量比{vol_ratio:.1f}，交投趋于活跃")
            elif vol_ratio > 3:
                score += 10
                reasons.append(f"量比{vol_ratio:.1f}，极度活跃")
                risks.append("量比过大，可能是短期情绪炒作")
            elif vol_ratio < 0.7:
                risks.append(f"量比{vol_ratio:.1f}，交投不活跃")
        except Exception as e:
            logger.debug(f"股性锁-量比计算失败: {e}")

        # 4. 量能趋势（20分）- 量能持续放大=股性趋于活跃
        try:
            if len(volume) >= 10:
                vol_ma5 = volume.iloc[-5:].mean()
                vol_ma10 = volume.iloc[-10:].mean()
                details["vol_ma5"] = round(vol_ma5, 0)
                details["vol_ma10"] = round(vol_ma10, 0)
                
                if vol_ma5 > vol_ma10 * 1.2:
                    score += 15
                    reasons.append("5日均量大于10日均量，量能持续放大")
                elif vol_ma5 > vol_ma10:
                    score += 8
                    reasons.append("5日均量略大于10日均量")
                else:
                    risks.append("量能萎缩，股性可能转弱")
                
                # 连续放量天数
                continuous_vol_up = 0
                for i in range(-1, -6, -1):
                    if abs(i) < len(volume) and volume.iloc[i] > volume.iloc[i-1]:
                        continuous_vol_up += 1
                    else:
                        break
                details["continuous_vol_up"] = continuous_vol_up
                if continuous_vol_up >= 3:
                    score += 5
                    reasons.append(f"连续{continuous_vol_up}日放量")
        except Exception as e:
            logger.debug(f"股性锁-量能趋势计算失败: {e}")

        # 换手率（如果有数据，作为活跃度参考）
        if quote and quote.get("turnover"):
            try:
                turnover = float(quote.get("turnover", 0))
                details["turnover"] = turnover
                if 3 <= turnover <= 15:
                    score += 5
                    reasons.append(f"换手率{turnover:.1f}%，交投活跃")
                elif turnover > 20:
                    risks.append(f"换手率过高（{turnover:.1f}%），可能出货")
            except:
                pass

        # 5. 当日振幅参考（活跃度补充）
        try:
            if len(high) >= 1 and len(low) >= 1 and current_price > 0:
                today_amp = (high.iloc[-1] - low.iloc[-1]) / current_price * 100
                details["today_amplitude"] = round(today_amp, 2)
                if today_amp >= 3:
                    score += 5
                    reasons.append(f"当日振幅{today_amp:.1f}%，短线活跃")
        except Exception as e:
            logger.debug(f"股性锁-当日振幅计算失败: {e}")

        score = max(0, min(100, round(score)))
        locked = score >= 60  # 股性锁门槛从50分提高到60分（回测发现点亮率100%，门槛太低失去筛选意义）

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
        第三把锁：资金锁（指南针官方规则：要红不要绿）
        核心：连续3日多空资金翻红（净流入）
        条件：
        - 连续3日量价齐升（价涨量增=资金翻红，无资金数据时的替代）
        - 近5日资金翻红天数
        - OBV能量潮持续上升
        - 量价配合健康
        """
        score = 0
        reasons = []
        risks = []
        details = {}

        # 1. 连续3日多空资金翻红（40分）- 核心条件
        # 有资金流向数据时用真实资金数据，没有时用连续3日量价齐升代替
        if capital_flow:
            try:
                main_net_inflow = capital_flow.get("main_net_inflow", 0)
                details["main_net_inflow"] = main_net_inflow
                if main_net_inflow > 0:
                    score += 10
                    reasons.append(f"当日主力资金净流入（{main_net_inflow/10000:.0f}万）")
                elif main_net_inflow < 0:
                    risks.append(f"当日主力资金净流出（{abs(main_net_inflow)/10000:.0f}万）")
            except Exception as e:
                logger.debug(f"资金锁-资金流向计算失败: {e}")
        
        # 用连续3日量价齐升判断"多空资金翻红"（无资金数据时的核心替代方案）
        try:
            if len(close) >= 4 and len(volume) >= 4:
                continuous_red_days = 0
                for i in range(-3, 0):
                    price_up = close.iloc[i] > close.iloc[i-1]
                    vol_up = volume.iloc[i] > volume.iloc[i-1]
                    # 翻红 = 股价上涨 + 成交量放大（量价齐升=资金流入）
                    if price_up and vol_up:
                        continuous_red_days += 1
                
                details["continuous_red_days"] = continuous_red_days
                
                if continuous_red_days >= 3:
                    score += 35
                    reasons.append(f"连续{continuous_red_days}日量价齐升，多空资金翻红")
                elif continuous_red_days == 2:
                    score += 22
                    reasons.append(f"连续{continuous_red_days}日量价齐升，资金趋于翻红")
                elif continuous_red_days == 1:
                    score += 10
                    reasons.append("近1日量价齐升")
                else:
                    risks.append("近3日无量价齐升，资金未翻红")
        except Exception as e:
            logger.debug(f"资金锁-连续翻红计算失败: {e}")

        # 2. 近5日资金翻红天数（25分）
        try:
            if len(close) >= 6 and len(volume) >= 6:
                red_days_5d = 0
                for i in range(-5, 0):
                    if close.iloc[i] > close.iloc[i-1] and volume.iloc[i] > volume.iloc[i-1]:
                        red_days_5d += 1
                
                details["red_days_5d"] = red_days_5d
                
                if red_days_5d >= 4:
                    score += 22
                    reasons.append(f"5日内{red_days_5d}日资金翻红，资金持续流入")
                elif red_days_5d >= 3:
                    score += 15
                    reasons.append(f"5日内{red_days_5d}日资金翻红")
                elif red_days_5d >= 2:
                    score += 8
                    reasons.append(f"5日内{red_days_5d}日资金翻红")
                else:
                    risks.append("5日内资金翻红天数不足")
        except Exception as e:
            logger.debug(f"资金锁-5日翻红计算失败: {e}")

        # 3. OBV能量潮趋势（20分）- OBV连续上升=资金持续流入
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
            
            if len(obv_series) >= 6:
                # OBV连续上升天数
                obv_continuous_up = 0
                for i in range(-1, -6, -1):
                    if abs(i) < len(obv_series) and obv_series.iloc[i] > obv_series.iloc[i-1]:
                        obv_continuous_up += 1
                    else:
                        break
                details["obv_continuous_up"] = obv_continuous_up
                
                # OBV 5日趋势
                obv_trend_5d = (obv_series.iloc[-1] - obv_series.iloc[-6]) / abs(obv_series.iloc[-6]) * 100 if obv_series.iloc[-6] != 0 else 0
                details["obv_trend_5d"] = round(obv_trend_5d, 2)
                
                if obv_continuous_up >= 3:
                    score += 15
                    reasons.append(f"OBV连续{obv_continuous_up}日上升，资金持续流入")
                elif obv_trend_5d > 5:
                    score += 12
                    reasons.append("OBV 5日显著上升，资金流入")
                elif obv_trend_5d > 0:
                    score += 8
                    reasons.append("OBV 5日上升")
                else:
                    risks.append("OBV下降，资金可能流出")
        except Exception as e:
            logger.debug(f"资金锁-OBV计算失败: {e}")

        # 4. 量价配合质量（15分）
        try:
            if len(close) >= 5 and len(volume) >= 5:
                price_up_5d = close.iloc[-1] > close.iloc[-5]
                vol_up_5d = volume.iloc[-5:].mean() > volume.iloc[-10:-5].mean() if len(volume) >= 10 else volume.iloc[-1] > volume.iloc[-5]
                details["price_up_5d"] = price_up_5d
                details["vol_up_5d"] = vol_up_5d
                
                if price_up_5d and vol_up_5d:
                    score += 12
                    reasons.append("5日量价齐升，资金面健康")
                elif price_up_5d and not vol_up_5d:
                    score += 4
                    risks.append("5日价涨量缩，资金跟进不足")
                else:
                    risks.append("5日量价配合不佳")
        except Exception as e:
            logger.debug(f"资金锁-量价质量计算失败: {e}")

        score = max(0, min(100, round(score)))
        locked = score >= 30  # 资金锁门槛从35分降低到30分（回测发现点亮率仅23.1%，门槛还是太高）

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
            if signal == "强烈买入":
                signal = "谨慎买入"
            elif signal == "买入":
                signal = "观望"

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
