"""
走势分析模块
提供专业的股票走势分析功能：
- 趋势判断（上升/下降/震荡，强/中/弱）
- 支撑位和压力位（动态计算）
- 走势形态识别（双底/双顶/头肩/三角形/箱体等）
- 均线系统分析
- 量价关系分析
- 走势评分和操作建议
"""
import logging
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from backend.analysis.indicators import (
    calc_ma_system, calc_macd, calc_kdj, calc_rsi,
    calc_bollinger, calc_volume_analysis, calc_support_resistance,
    calc_atr, calc_trend, calc_momentum
)

logger = logging.getLogger(__name__)


class TrendAnalyzer:
    """走势分析器"""

    def __init__(self):
        pass

    def analyze(self, kline: pd.DataFrame, quote: Optional[Dict] = None) -> Dict:
        """
        综合走势分析
        返回：{
            trend: {direction, strength, score, description},
            support_resistance: {support, resistance, key_levels},
            patterns: [{name, confidence, description}],
            ma_analysis: {alignment, position, pressure_support},
            volume_price: {relation, description, score},
            overall_score: int,
            operation_suggestion: str,
            key_points: [],
        }
        """
        if kline is None or len(kline) < 30:
            return self._empty_result("K线数据不足，需要至少30根K线")

        close = kline["close"]
        high = kline["high"]
        low = kline["low"]
        volume = kline["volume"]
        current_price = quote.get("price", close.iloc[-1]) if quote else close.iloc[-1]

        # 1. 趋势分析
        trend = self._analyze_trend(close, high, low, current_price)

        # 2. 支撑压力位
        sr = self._analyze_support_resistance(high, low, close, current_price)

        # 3. 走势形态
        patterns = self._detect_patterns(high, low, close, volume)

        # 4. 均线分析
        ma_analysis = self._analyze_ma_system(close, current_price)

        # 5. 量价关系
        vp = self._analyze_volume_price(close, volume)

        # 6. 综合评分
        overall_score = self._calc_overall_score(trend, sr, patterns, ma_analysis, vp)

        # 7. 操作建议
        suggestion = self._generate_suggestion(trend, sr, patterns, ma_analysis, vp, overall_score, current_price)

        # 8. 关键点位
        key_points = self._generate_key_points(trend, sr, ma_analysis, current_price)

        return {
            "trend": trend,
            "support_resistance": sr,
            "patterns": patterns,
            "ma_analysis": ma_analysis,
            "volume_price": vp,
            "overall_score": overall_score,
            "operation_suggestion": suggestion,
            "key_points": key_points,
        }

    def _analyze_trend(self, close: pd.Series, high: pd.Series, low: pd.Series,
                        current_price: float) -> Dict:
        """趋势分析"""
        score = 50
        direction = "震荡"
        strength = "中性"
        reasons = []

        # 均线趋势
        ma = calc_ma_system(close)
        if ma.get("bullish_alignment"):
            score += 20
            direction = "上升"
            strength = "强"
            reasons.append("均线多头排列，上升趋势明确")
        elif ma.get("bearish_alignment"):
            score -= 20
            direction = "下降"
            strength = "强"
            reasons.append("均线空头排列，下降趋势明确")
        else:
            reasons.append("均线交织，趋势不明")

        # 趋势指标
        trend = calc_trend(close)
        trend_score = trend.get("trend_score", 50)
        if trend_score >= 75:
            score += 15
            if direction != "下降":
                direction = "上升"
            strength = "强"
            reasons.append(f"趋势指标强势（{trend.get('trend')}）")
        elif trend_score >= 60:
            score += 8
            if direction != "下降":
                direction = "上升"
            strength = "中"
            reasons.append(f"趋势指标偏多（{trend.get('trend')}）")
        elif trend_score <= 35:
            score -= 15
            if direction != "上升":
                direction = "下降"
            strength = "强"
            reasons.append(f"趋势指标弱势（{trend.get('trend')}）")
        elif trend_score <= 45:
            score -= 8
            if direction != "上升":
                direction = "下降"
            strength = "中"
            reasons.append(f"趋势指标偏空（{trend.get('trend')}）")

        # 高低点分析
        if len(high) >= 20:
            recent_high = high.iloc[-10:].max()
            prev_high = high.iloc[-20:-10].max()
            recent_low = low.iloc[-10:].min()
            prev_low = low.iloc[-20:-10].min()

            higher_high = recent_high > prev_high
            higher_low = recent_low > prev_low

            if higher_high and higher_low:
                score += 10
                reasons.append("高低点同步抬高，上升趋势健康")
            elif not higher_high and not higher_low:
                score -= 10
                reasons.append("高低点同步降低，下降趋势延续")
            elif higher_high and not higher_low:
                reasons.append("高点抬高但低点降低，震荡加剧")
            else:
                reasons.append("高点降低但低点抬高，收敛震荡")

        # MACD趋势
        macd = calc_macd(close)
        if macd.get("dif", 0) > macd.get("dea", 0) and macd.get("dif", 0) > 0:
            score += 8
            reasons.append("MACD多头排列，中期趋势向上")
        elif macd.get("dif", 0) < macd.get("dea", 0) and macd.get("dif", 0) < 0:
            score -= 8
            reasons.append("MACD空头排列，中期趋势向下")

        score = max(0, min(100, round(score)))

        # 描述
        if score >= 75:
            description = f"强势{direction}趋势，趋势健康，顺势操作"
        elif score >= 60:
            description = f"温和{direction}趋势，可逢低布局"
        elif score >= 45:
            description = "震荡整理，方向不明，观望为主"
        elif score >= 30:
            description = f"偏弱{direction}趋势，谨慎操作"
        else:
            description = f"弱势{direction}趋势，规避为主"

        return {
            "direction": direction,
            "strength": strength,
            "score": score,
            "reasons": reasons,
            "description": description,
        }

    def _analyze_support_resistance(self, high: pd.Series, low: pd.Series,
                                      close: pd.Series, current_price: float) -> Dict:
        """支撑压力位分析"""
        levels = []

        # 方法1：前期高低点
        if len(high) >= 20:
            # 近20日高点作为压力
            resistance_20d = round(high.iloc[-20:].max(), 2)
            support_20d = round(low.iloc[-20:].min(), 2)
            levels.append({"price": resistance_20d, "type": "压力", "strength": "中", "source": "20日高点"})
            levels.append({"price": support_20d, "type": "支撑", "strength": "中", "source": "20日低点"})

        # 方法2：均线支撑压力
        ma = calc_ma_system(close)
        for ma_name in ["ma5", "ma10", "ma20", "ma60"]:
            ma_val = ma.get(ma_name)
            if ma_val:
                if ma_val > current_price:
                    levels.append({"price": round(ma_val, 2), "type": "压力", "strength": "中", "source": ma_name.upper()})
                else:
                    levels.append({"price": round(ma_val, 2), "type": "支撑", "strength": "中", "source": ma_name.upper()})

        # 方法3：布林带
        boll = calc_bollinger(close)
        if boll.get("upper"):
            levels.append({"price": round(boll["upper"], 2), "type": "压力", "strength": "强", "source": "布林上轨"})
        if boll.get("lower"):
            levels.append({"price": round(boll["lower"], 2), "type": "支撑", "strength": "强", "source": "布林下轨"})
        if boll.get("middle"):
            levels.append({"price": round(boll["middle"], 2), "type": "中轨", "strength": "中", "source": "布林中轨"})

        # 方法4：整数关口
        for level in [int(current_price), int(current_price) + 1, int(current_price) - 1]:
            if level > 0:
                levels.append({"price": float(level), "type": "心理关口", "strength": "弱", "source": "整数关口"})

        # 排序并去重
        supports = sorted([l for l in levels if l["type"] == "支撑" and l["price"] < current_price],
                         key=lambda x: x["price"], reverse=True)
        resistances = sorted([l for l in levels if l["type"] == "压力" and l["price"] > current_price],
                            key=lambda x: x["price"])

        # 最近的支撑和压力
        nearest_support = supports[0] if supports else None
        nearest_resistance = resistances[0] if resistances else None

        # 位置判断
        if nearest_support and nearest_resistance:
            total_range = nearest_resistance["price"] - nearest_support["price"]
            if total_range > 0:
                position = (current_price - nearest_support["price"]) / total_range * 100
                if position > 70:
                    position_desc = "接近压力位，注意回调风险"
                elif position < 30:
                    position_desc = "接近支撑位，关注反弹机会"
                else:
                    position_desc = "处于支撑压力中间，震荡整理"
            else:
                position_desc = "支撑压力位接近，方向选择中"
        else:
            position_desc = "支撑压力位不明确"

        return {
            "nearest_support": nearest_support,
            "nearest_resistance": nearest_resistance,
            "supports": supports[:5],
            "resistances": resistances[:5],
            "all_levels": levels,
            "position_description": position_desc,
        }

    def _detect_patterns(self, high: pd.Series, low: pd.Series, close: pd.Series,
                          volume: pd.Series) -> List[Dict]:
        """走势形态识别"""
        patterns = []

        if len(close) < 30:
            return patterns

        # 1. 双底形态（W底）
        if self._detect_double_bottom(high, low, close, volume):
            patterns.append({
                "name": "双底（W底）",
                "type": "看涨",
                "confidence": 70,
                "description": "形成双底形态，是较强的看涨反转信号，突破颈线后确认",
            })

        # 2. 双顶形态（M头）
        if self._detect_double_top(high, low, close, volume):
            patterns.append({
                "name": "双顶（M头）",
                "type": "看跌",
                "confidence": 70,
                "description": "形成双顶形态，是较强的看跌反转信号，跌破颈线后确认",
            })

        # 3. 头肩底
        if self._detect_head_shoulders_bottom(high, low, close):
            patterns.append({
                "name": "头肩底",
                "type": "看涨",
                "confidence": 80,
                "description": "形成头肩底形态，是经典的看涨反转形态，可靠性较高",
            })

        # 4. 头肩顶
        if self._detect_head_shoulders_top(high, low, close):
            patterns.append({
                "name": "头肩顶",
                "type": "看跌",
                "confidence": 80,
                "description": "形成头肩顶形态，是经典的看跌反转形态，可靠性较高",
            })

        # 5. 箱体震荡
        if self._detect_box_pattern(high, low, close):
            patterns.append({
                "name": "箱体震荡",
                "type": "中性",
                "confidence": 60,
                "description": "股价在箱体内震荡，高抛低吸操作，突破方向后顺势",
            })

        # 6. 上升三角形
        if self._detect_ascending_triangle(high, low, close):
            patterns.append({
                "name": "上升三角形",
                "type": "看涨",
                "confidence": 65,
                "description": "形成上升三角形，看涨整理形态，突破上沿后上涨概率大",
            })

        # 7. 下降三角形
        if self._detect_descending_triangle(high, low, close):
            patterns.append({
                "name": "下降三角形",
                "type": "看跌",
                "confidence": 65,
                "description": "形成下降三角形，看跌整理形态，跌破下沿后下跌概率大",
            })

        # 8. 均线粘合
        if self._detect_ma_convergence(close):
            patterns.append({
                "name": "均线粘合",
                "type": "变盘",
                "confidence": 75,
                "description": "多条均线粘合，即将选择方向，关注突破方向",
            })

        return patterns

    def _detect_double_bottom(self, high, low, close, volume) -> bool:
        """双底检测"""
        if len(low) < 20:
            return False
        # 简化检测：近20日内有两个相近的低点
        recent_lows = low.iloc[-20:].values
        if len(recent_lows) < 10:
            return False
        # 找两个最低点
        sorted_idx = np.argsort(recent_lows)[:2]
        if abs(sorted_idx[0] - sorted_idx[1]) < 3:
            return False
        low1 = recent_lows[sorted_idx[0]]
        low2 = recent_lows[sorted_idx[1]]
        if abs(low1 - low2) / low1 < 0.03:  # 两个低点相差不超过3%
            # 中间有反弹
            mid_idx = (sorted_idx[0] + sorted_idx[1]) // 2
            if mid_idx < len(recent_lows) and recent_lows[mid_idx] > max(low1, low2) * 1.02:
                return True
        return False

    def _detect_double_top(self, high, low, close, volume) -> bool:
        """双顶检测"""
        if len(high) < 20:
            return False
        recent_highs = high.iloc[-20:].values
        if len(recent_highs) < 10:
            return False
        sorted_idx = np.argsort(recent_highs)[-2:]
        if abs(sorted_idx[0] - sorted_idx[1]) < 3:
            return False
        high1 = recent_highs[sorted_idx[0]]
        high2 = recent_highs[sorted_idx[1]]
        if abs(high1 - high2) / high1 < 0.03:
            mid_idx = (sorted_idx[0] + sorted_idx[1]) // 2
            if mid_idx < len(recent_highs) and recent_highs[mid_idx] < min(high1, high2) * 0.98:
                return True
        return False

    def _detect_head_shoulders_bottom(self, high, low, close) -> bool:
        """头肩底检测（简化）"""
        if len(low) < 30:
            return False
        # 简化：中间低点明显低于两侧低点
        recent_lows = low.iloc[-30:].values
        mid = len(recent_lows) // 2
        left_low = min(recent_lows[:mid])
        right_low = min(recent_lows[mid:])
        head_low = min(recent_lows[mid-5:mid+5])
        if head_low < left_low * 0.97 and head_low < right_low * 0.97:
            return True
        return False

    def _detect_head_shoulders_top(self, high, low, close) -> bool:
        """头肩顶检测（简化）"""
        if len(high) < 30:
            return False
        recent_highs = high.iloc[-30:].values
        mid = len(recent_highs) // 2
        left_high = max(recent_highs[:mid])
        right_high = max(recent_highs[mid:])
        head_high = max(recent_highs[mid-5:mid+5])
        if head_high > left_high * 1.03 and head_high > right_high * 1.03:
            return True
        return False

    def _detect_box_pattern(self, high, low, close) -> bool:
        """箱体震荡检测"""
        if len(close) < 20:
            return False
        recent_high = high.iloc[-20:].max()
        recent_low = low.iloc[-20:].min()
        if recent_high > 0 and (recent_high - recent_low) / recent_low < 0.15:
            # 振幅小于15%，且多次触及上下沿
            return True
        return False

    def _detect_ascending_triangle(self, high, low, close) -> bool:
        """上升三角形检测"""
        if len(close) < 20:
            return False
        # 高点基本水平，低点不断抬高
        recent_highs = high.iloc[-20:].values
        recent_lows = low.iloc[-20:].values
        high_std = np.std(recent_highs[-10:]) / np.mean(recent_highs[-10:])
        low_trend = (recent_lows[-1] - recent_lows[0]) / recent_lows[0]
        if high_std < 0.03 and low_trend > 0.02:
            return True
        return False

    def _detect_descending_triangle(self, high, low, close) -> bool:
        """下降三角形检测"""
        if len(close) < 20:
            return False
        recent_highs = high.iloc[-20:].values
        recent_lows = low.iloc[-20:].values
        low_std = np.std(recent_lows[-10:]) / np.mean(recent_lows[-10:])
        high_trend = (recent_highs[-1] - recent_highs[0]) / recent_highs[0]
        if low_std < 0.03 and high_trend < -0.02:
            return True
        return False

    def _detect_ma_convergence(self, close) -> bool:
        """均线粘合检测"""
        if len(close) < 60:
            return False
        ma5 = close.rolling(5).mean().iloc[-1]
        ma10 = close.rolling(10).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        if all([ma5, ma10, ma20, ma60]):
            max_ma = max(ma5, ma10, ma20, ma60)
            min_ma = min(ma5, ma10, ma20, ma60)
            if max_ma > 0 and (max_ma - min_ma) / min_ma < 0.03:
                return True
        return False

    def _analyze_ma_system(self, close: pd.Series, current_price: float) -> Dict:
        """均线系统分析"""
        ma = calc_ma_system(close)

        # 排列状态
        if ma.get("bullish_alignment"):
            alignment = "多头排列"
            alignment_score = 90
        elif ma.get("bearish_alignment"):
            alignment = "空头排列"
            alignment_score = 10
        else:
            alignment = "交织排列"
            alignment_score = 50

        # 股价位置
        ma5 = ma.get("ma5")
        ma10 = ma.get("ma10")
        ma20 = ma.get("ma20")
        ma60 = ma.get("ma60")

        above_count = sum([
            1 if ma5 and current_price > ma5 else 0,
            1 if ma10 and current_price > ma10 else 0,
            1 if ma20 and current_price > ma20 else 0,
            1 if ma60 and current_price > ma60 else 0,
        ])

        if above_count >= 3:
            position = "均线之上"
            position_score = 80
        elif above_count >= 2:
            position = "均线之间"
            position_score = 50
        else:
            position = "均线之下"
            position_score = 20

        # 均线支撑压力
        pressures = []
        supports = []
        for name, val in [("MA5", ma5), ("MA10", ma10), ("MA20", ma20), ("MA60", ma60)]:
            if val:
                if val > current_price:
                    pressures.append({"name": name, "value": round(val, 2)})
                else:
                    supports.append({"name": name, "value": round(val, 2)})

        return {
            "alignment": alignment,
            "alignment_score": alignment_score,
            "position": position,
            "position_score": position_score,
            "above_count": above_count,
            "pressures": sorted(pressures, key=lambda x: x["value"]),
            "supports": sorted(supports, key=lambda x: x["value"], reverse=True),
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "ma60": ma60,
        }

    def _analyze_volume_price(self, close: pd.Series, volume: pd.Series) -> Dict:
        """量价关系分析"""
        if len(close) < 10 or len(volume) < 10:
            return {"relation": "数据不足", "description": "数据不足", "score": 50}

        # 近5日价量变化
        price_change = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100
        vol_change = (volume.iloc[-5:].mean() - volume.iloc[-10:-5].mean()) / volume.iloc[-10:-5].mean() * 100 if len(volume) >= 10 else 0

        # 量价关系判断
        if price_change > 2 and vol_change > 20:
            relation = "价涨量增"
            description = "价格上涨伴随成交量放大，资金积极入场，上涨动能充足"
            score = 85
        elif price_change > 2 and vol_change < -10:
            relation = "价涨量缩"
            description = "价格上涨但成交量萎缩，上涨动能不足，需警惕回调"
            score = 45
        elif price_change < -2 and vol_change > 20:
            relation = "价跌量增"
            description = "价格下跌伴随成交量放大，资金出逃，下跌动能较强"
            score = 20
        elif price_change < -2 and vol_change < -10:
            relation = "价跌量缩"
            description = "价格下跌但成交量萎缩，抛压减轻，可能接近底部"
            score = 55
        elif abs(price_change) < 2 and vol_change > 20:
            relation = "价平量增"
            description = "价格平稳但成交量放大，多空分歧加大，关注方向选择"
            score = 50
        elif abs(price_change) < 2 and vol_change < -10:
            relation = "价平量缩"
            description = "价格平稳且成交量萎缩，市场观望情绪浓厚"
            score = 50
        else:
            relation = "量价正常"
            description = "量价关系正常，无明显异常信号"
            score = 60

        return {
            "relation": relation,
            "description": description,
            "score": score,
            "price_change_5d": round(price_change, 2),
            "volume_change_5d": round(vol_change, 2),
        }

    def _calc_overall_score(self, trend, sr, patterns, ma_analysis, vp) -> int:
        """综合走势评分"""
        score = 50

        # 趋势（30%）
        score += (trend["score"] - 50) * 0.3

        # 均线（25%）
        ma_score = (ma_analysis["alignment_score"] + ma_analysis["position_score"]) / 2
        score += (ma_score - 50) * 0.25

        # 量价（20%）
        score += (vp["score"] - 50) * 0.2

        # 形态（15%）
        bullish_patterns = [p for p in patterns if p["type"] == "看涨"]
        bearish_patterns = [p for p in patterns if p["type"] == "看跌"]
        pattern_score = 50
        for p in bullish_patterns:
            pattern_score += p["confidence"] * 0.1
        for p in bearish_patterns:
            pattern_score -= p["confidence"] * 0.1
        score += (pattern_score - 50) * 0.15

        # 支撑压力位置（10%）
        if "接近支撑" in sr.get("position_description", ""):
            score += 5
        elif "接近压力" in sr.get("position_description", ""):
            score -= 5

        return max(0, min(100, round(score)))

    def _generate_suggestion(self, trend, sr, patterns, ma_analysis, vp,
                              overall_score, current_price) -> str:
        """生成操作建议"""
        suggestions = []

        # 基于评分的总体建议
        if overall_score >= 75:
            suggestions.append("走势强劲，可积极做多，顺势持有")
        elif overall_score >= 60:
            suggestions.append("走势偏强，可逢低布局，设置止损")
        elif overall_score >= 45:
            suggestions.append("走势震荡，观望为主，高抛低吸")
        elif overall_score >= 30:
            suggestions.append("走势偏弱，谨慎操作，控制仓位")
        else:
            suggestions.append("走势弱势，规避为主，等待企稳")

        # 趋势建议
        if trend["direction"] == "上升":
            suggestions.append(f"上升趋势中，支撑位{sr['nearest_support']['price'] if sr['nearest_support'] else '?'}元附近可考虑低吸")
        elif trend["direction"] == "下降":
            suggestions.append(f"下降趋势中，压力位{sr['nearest_resistance']['price'] if sr['nearest_resistance'] else '?'}元附近可考虑减仓")

        # 形态建议
        bullish = [p for p in patterns if p["type"] == "看涨"]
        bearish = [p for p in patterns if p["type"] == "看跌"]
        if bullish:
            suggestions.append(f"出现看涨形态：{bullish[0]['name']}，关注确认信号")
        if bearish:
            suggestions.append(f"出现看跌形态：{bearish[0]['name']}，注意风险控制")

        # 量价建议
        if vp["relation"] == "价涨量增":
            suggestions.append("量价配合良好，可继续持有")
        elif vp["relation"] == "价涨量缩":
            suggestions.append("量价背离，警惕冲高回落")
        elif vp["relation"] == "价跌量增":
            suggestions.append("放量下跌，及时止损离场")

        return "；".join(suggestions)

    def _generate_key_points(self, trend, sr, ma_analysis, current_price) -> List[str]:
        """生成关键点位"""
        points = []

        if sr.get("nearest_support"):
            points.append(f"第一支撑：{sr['nearest_support']['price']}元（{sr['nearest_support']['source']}）")
        if sr.get("nearest_resistance"):
            points.append(f"第一压力：{sr['nearest_resistance']['price']}元（{sr['nearest_resistance']['source']}）")

        if ma_analysis.get("supports"):
            for s in ma_analysis["supports"][:2]:
                points.append(f"{s['name']}支撑：{s['value']}元")
        if ma_analysis.get("pressures"):
            for p in ma_analysis["pressures"][:2]:
                points.append(f"{p['name']}压力：{p['value']}元")

        return points

    def _empty_result(self, reason: str) -> Dict:
        """空结果"""
        return {
            "trend": {"direction": "未知", "strength": "未知", "score": 0, "reasons": [reason], "description": reason},
            "support_resistance": {"nearest_support": None, "nearest_resistance": None, "supports": [], "resistances": [], "position_description": reason},
            "patterns": [],
            "ma_analysis": {"alignment": "未知", "position": "未知", "above_count": 0},
            "volume_price": {"relation": "未知", "description": reason, "score": 0},
            "overall_score": 0,
            "operation_suggestion": reason,
            "key_points": [],
        }


# 全局单例
trend_analyzer = TrendAnalyzer()
