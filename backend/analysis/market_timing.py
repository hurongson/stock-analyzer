"""
市场择时模块
分析大盘趋势，给出仓位建议和市场情绪判断
参考指数：上证指数(000001)、深证成指(399001)、创业板指(399006)
"""
import logging
from typing import Dict, Any, Optional
from backend.data.collector import collector
from backend.analysis.indicators import (
    calc_trend, calc_macd, calc_rsi_system, calc_kdj,
    calc_bollinger, calc_volume_analysis, calc_ma_system,
    calc_atr, calc_obv
)

logger = logging.getLogger(__name__)

# 指数代码映射
INDEX_MAP = {
    "sh": "000001",      # 上证指数
    "sz": "399001",      # 深证成指
    "cyb": "399006",     # 创业板指
}

INDEX_NAMES = {
    "000001": "上证指数",
    "399001": "深证成指",
    "399006": "创业板指",
}


def analyze_index(index_code: str, days: int = 120) -> Optional[Dict]:
    """分析单个指数"""
    try:
        df = collector.get_daily_kline(index_code, days=days)
        if df is None or df.empty or len(df) < 30:
            return None

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        result = {
            "code": index_code,
            "name": INDEX_NAMES.get(index_code, index_code),
            "price": round(close.iloc[-1], 2),
            "pct_change": round(df["pct_change"].iloc[-1], 2) if "pct_change" in df.columns else 0,
            "trend": calc_trend(close),
            "macd": {k: round(v, 4) if isinstance(v, (int, float)) else v
                    for k, v in calc_macd(close).items() if "series" not in k},
            "rsi": calc_rsi_system(close),
            "kdj": {k: round(v, 2) if isinstance(v, (int, float)) else v
                   for k, v in calc_kdj(high, low, close).items()},
            "bollinger": {k: round(v, 2) if isinstance(v, (int, float)) else v
                          for k, v in calc_bollinger(close).items()},
            "volume": calc_volume_analysis(volume, close),
            "atr": calc_atr(high, low, close),
            "obv": calc_obv(close, volume),
        }
        return result
    except Exception as e:
        logger.error(f"分析指数 {index_code} 失败: {e}")
        return None


def calc_market_sentiment(index_analysis: Dict) -> Dict:
    """计算市场情绪"""
    if not index_analysis:
        return {"sentiment": "未知", "sentiment_score": 50, "position": "50%"}

    score = 50
    reasons = []

    # 上证指数为主
    sh = index_analysis.get("sh")
    if not sh:
        return {"sentiment": "数据不足", "sentiment_score": 50, "position": "50%", "reasons": ["指数数据不足"]}

    # 1. 趋势（权重30%）
    trend_score = sh["trend"]["trend_score"]
    score += (trend_score - 50) * 0.3
    if trend_score >= 75:
        reasons.append(f"大盘{sh['trend']['trend']}")
    elif trend_score <= 35:
        reasons.append(f"大盘{sh['trend']['trend']}")

    # 2. MACD（权重20%）
    if sh["macd"].get("golden_cross"):
        score += 10
        reasons.append("MACD金叉")
    elif sh["macd"].get("death_cross"):
        score -= 10
        reasons.append("MACD死叉")
    if sh["macd"]["dif"] > sh["macd"]["dea"]:
        score += 5
    else:
        score -= 5

    # 3. RSI（权重15%）
    rsi6 = sh["rsi"].get("rsi6") or 50
    if rsi6 > 80:
        score -= 10
        reasons.append("RSI超买（警惕回调）")
    elif rsi6 < 20:
        score += 8
        reasons.append("RSI超卖（反弹机会）")
    elif 40 <= rsi6 <= 60:
        score += 3

    # 4. 成交量（权重15%）
    vol_ratio = sh["volume"]["volume_ratio"]
    vp = sh["volume"].get("volume_price", "")
    if "放量上涨" in vp:
        score += 8
        reasons.append("放量上涨（资金入场）")
    elif "放量下跌" in vp:
        score -= 8
        reasons.append("放量下跌（资金出逃）")
    elif "缩量下跌" in vp:
        score += 3
        reasons.append("缩量下跌（抛压减轻）")

    # 5. 创业板/深证确认（权重10%）
    sz = index_analysis.get("sz")
    cyb = index_analysis.get("cyb")
    if sz and cyb:
        sz_trend = sz["trend"]["trend_score"]
        cyb_trend = cyb["trend"]["trend_score"]
        if sz_trend > 60 and cyb_trend > 60:
            score += 5
            reasons.append("深市/创业板同步走强")
        elif sz_trend < 40 and cyb_trend < 40:
            score -= 5
            reasons.append("深市/创业板同步走弱")

    # 6. 布林带位置（权重10%）
    boll_pos = sh["bollinger"]["position"]
    if boll_pos > 90:
        score -= 5
        reasons.append("指数逼近布林上轨（压力大）")
    elif boll_pos < 10:
        score += 5
        reasons.append("指数触及布林下轨（支撑强）")

    score = max(0, min(100, round(score)))

    # 情绪判断
    if score >= 80:
        sentiment = "极度乐观"
        position = "80-90%"
    elif score >= 65:
        sentiment = "偏乐观"
        position = "60-70%"
    elif score >= 50:
        sentiment = "中性偏多"
        position = "50-60%"
    elif score >= 35:
        sentiment = "中性偏空"
        position = "30-40%"
    elif score >= 20:
        sentiment = "偏悲观"
        position = "20-30%"
    else:
        sentiment = "极度悲观"
        position = "10-20%"

    return {
        "sentiment": sentiment,
        "sentiment_score": score,
        "position": position,
        "reasons": reasons,
    }


def market_timing() -> Dict[str, Any]:
    """
    市场择时主函数
    分析三大指数，给出市场情绪和仓位建议
    """
    logger.info("开始市场择时分析...")

    index_analysis = {}
    for key, code in INDEX_MAP.items():
        logger.info(f"分析指数: {INDEX_NAMES.get(code, code)}({code})")
        result = analyze_index(code)
        if result:
            index_analysis[key] = result

    if not index_analysis:
        return {
            "error": "无法获取指数数据",
            "sentiment": "未知",
            "sentiment_score": 50,
            "position": "50%",
        }

    sentiment = calc_market_sentiment(index_analysis)

    result = {
        "indices": index_analysis,
        "sentiment": sentiment["sentiment"],
        "sentiment_score": sentiment["sentiment_score"],
        "position": sentiment["position"],
        "reasons": sentiment["reasons"],
    }

    logger.info(f"市场择时完成: {result['sentiment']}({result['sentiment_score']}分), 建议仓位{result['position']}")
    return result


# 全局单例
class MarketTiming:
    """市场择时单例"""
    _instance = None
    _cache = None
    _cache_time = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def analyze(self, force_refresh: bool = False) -> Dict:
        """获取市场择时分析结果（缓存5分钟）"""
        import time
        now = time.time()
        if not force_refresh and self._cache and self._cache_time and (now - self._cache_time) < 300:
            return self._cache
        self._cache = market_timing()
        self._cache_time = now
        return self._cache


market_timing_instance = MarketTiming()
