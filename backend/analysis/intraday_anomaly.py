"""
盘中异动监控模块（表2）
默认保持静默，只有出现以下情况时提醒：
- 板块级转强
- 成交显著异常
- 股价明显领先基本面
- 板块扩散明显下降
- 公司出现重要基本面变化
无法确认原因时明确写："暂未确认。"
"""

import logging
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class IntradayAnomalyMonitor:
    """盘中异动监控器"""

    def __init__(self):
        self.anomalies = []
        self.last_check_time = None

    def check_anomalies(self, market_data: Dict, stock_data: List[Dict]) -> Dict:
        """
        检查盘中异动
        返回：{has_anomaly: bool, anomalies: [...], summary: str}
        """
        self.anomalies = []
        self.last_check_time = datetime.now()

        # 1. 检查板块级转强
        self._check_sector_strength(market_data, stock_data)

        # 2. 检查成交显著异常
        self._check_volume_anomaly(stock_data)

        # 3. 检查股价明显领先基本面
        self._check_price_fundamental_divergence(stock_data)

        # 4. 检查板块扩散明显下降
        self._check_sector_diffusion_decline(market_data, stock_data)

        # 5. 检查公司重要基本面变化
        self._check_fundamental_change(stock_data)

        has_anomaly = len(self.anomalies) > 0
        summary = self._generate_summary()

        return {
            "has_anomaly": has_anomaly,
            "anomaly_count": len(self.anomalies),
            "anomalies": self.anomalies,
            "summary": summary,
            "check_time": self.last_check_time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _check_sector_strength(self, market_data: Dict, stock_data: List[Dict]):
        """检查板块级转强"""
        try:
            # 统计各行业涨幅
            sector_performance = {}
            for stock in stock_data:
                industry = stock.get("industry", "未知")
                pct_change = stock.get("pct_change", 0)
                if industry not in sector_performance:
                    sector_performance[industry] = {"stocks": [], "avg_pct": 0}
                sector_performance[industry]["stocks"].append(pct_change)

            # 计算各行业平均涨幅
            for industry, data in sector_performance.items():
                if data["stocks"]:
                    data["avg_pct"] = sum(data["stocks"]) / len(data["stocks"])
                    data["count"] = len(data["stocks"])

            # 找出涨幅前3的行业（板块级转强）
            top_sectors = sorted(
                sector_performance.items(),
                key=lambda x: x[1]["avg_pct"],
                reverse=True
            )[:3]

            for industry, data in top_sectors:
                if data["avg_pct"] > 2 and data["count"] >= 3:
                    # 找出该行业的领涨股
                    sector_stocks = [s for s in stock_data if s.get("industry") == industry]
                    sector_stocks.sort(key=lambda x: x.get("pct_change", 0), reverse=True)
                    leader = sector_stocks[0] if sector_stocks else None

                    reason = "暂未确认。"
                    if leader:
                        reason = f"领涨股{leader.get('name', '')}({leader.get('code', '')})涨幅{leader.get('pct_change', 0):.1f}%"

                    self.anomalies.append({
                        "type": "板块级转强",
                        "level": "high",
                        "industry": industry,
                        "avg_pct": round(data["avg_pct"], 2),
                        "stock_count": data["count"],
                        "leader": leader.get("name", "") if leader else "",
                        "reason": reason,
                        "description": f"{industry}板块平均涨幅{data['avg_pct']:.1f}%，{data['count']}只股票上涨",
                    })
                    logger.info(f"板块级转强: {industry} +{data['avg_pct']:.1f}%")

        except Exception as e:
            logger.warning(f"检查板块级转强失败: {e}")

    def _check_volume_anomaly(self, stock_data: List[Dict]):
        """检查成交显著异常"""
        try:
            for stock in stock_data[:50]:  # 只检查前50只活跃股票
                volume_ratio = stock.get("volume_ratio", 0)
                turnover = stock.get("turnover", 0)
                pct_change = stock.get("pct_change", 0)

                # 量比显著异常（>3）
                if volume_ratio > 3:
                    reason = "暂未确认。"
                    if pct_change > 3:
                        reason = "放量上涨，资金关注度提升"
                    elif pct_change < -3:
                        reason = "放量下跌，可能有资金出逃"

                    self.anomalies.append({
                        "type": "成交显著异常",
                        "level": "medium",
                        "code": stock.get("code", ""),
                        "name": stock.get("name", ""),
                        "volume_ratio": round(volume_ratio, 2),
                        "turnover": round(turnover, 2),
                        "pct_change": round(pct_change, 2),
                        "reason": reason,
                        "description": f"{stock.get('name', '')}量比{volume_ratio:.1f}，换手率{turnover:.1f}%，涨幅{pct_change:+.1f}%",
                    })
                    logger.info(f"成交异常: {stock.get('name')} 量比{volume_ratio:.1f}")

                # 限制异常数量
                if len([a for a in self.anomalies if a["type"] == "成交显著异常"]) >= 5:
                    break

        except Exception as e:
            logger.warning(f"检查成交异常失败: {e}")

    def _check_price_fundamental_divergence(self, stock_data: List[Dict]):
        """检查股价明显领先基本面"""
        try:
            for stock in stock_data[:30]:
                pct_change = stock.get("pct_change", 0)
                price = stock.get("price", 0)
                news_impact = stock.get("news_impact", {})
                news_score = news_impact.get("score", 50)

                # 股价大幅上涨但消息面中性或利空（股价领先基本面）
                if pct_change > 5 and news_score < 50:
                    self.anomalies.append({
                        "type": "股价明显领先基本面",
                        "level": "medium",
                        "code": stock.get("code", ""),
                        "name": stock.get("name", ""),
                        "pct_change": round(pct_change, 2),
                        "news_score": news_score,
                        "reason": f"股价上涨{pct_change:.1f}%，但消息面评分仅{news_score}分，可能存在预期差或题材炒作",
                        "description": f"{stock.get('name', '')}涨幅{pct_change:+.1f}%，消息面评分{news_score}分",
                    })
                    logger.info(f"股价领先基本面: {stock.get('name')} +{pct_change:.1f}%")

                if len([a for a in self.anomalies if a["type"] == "股价明显领先基本面"]) >= 3:
                    break

        except Exception as e:
            logger.warning(f"检查股价领先基本面失败: {e}")

    def _check_sector_diffusion_decline(self, market_data: Dict, stock_data: List[Dict]):
        """检查板块扩散明显下降"""
        try:
            # 简化判断：如果上涨股票数量少于下跌股票数量的30%，说明板块扩散下降
            up_count = sum(1 for s in stock_data if s.get("pct_change", 0) > 0)
            down_count = sum(1 for s in stock_data if s.get("pct_change", 0) < 0)
            total = len(stock_data)

            if total > 0 and down_count > 0:
                diffusion_ratio = up_count / down_count
                if diffusion_ratio < 0.3:
                    self.anomalies.append({
                        "type": "板块扩散明显下降",
                        "level": "high",
                        "up_count": up_count,
                        "down_count": down_count,
                        "diffusion_ratio": round(diffusion_ratio, 2),
                        "reason": f"上涨{up_count}只，下跌{down_count}只，涨跌比{diffusion_ratio:.2f}，市场情绪偏弱",
                        "description": f"上涨{up_count}只，下跌{down_count}只，涨跌比{diffusion_ratio:.2f}",
                    })
                    logger.info(f"板块扩散下降: 涨跌比{diffusion_ratio:.2f}")

        except Exception as e:
            logger.warning(f"检查板块扩散下降失败: {e}")

    def _check_fundamental_change(self, stock_data: List[Dict]):
        """检查公司重要基本面变化"""
        try:
            for stock in stock_data[:30]:
                news_impact = stock.get("news_impact", {})
                news_score = news_impact.get("score", 50)
                news_level = news_impact.get("level", "中性")
                news_reasons = news_impact.get("reasons", [])

                # 消息面重大利好或利空
                if news_score >= 75 or news_score <= 25:
                    direction = "利好" if news_score >= 75 else "利空"
                    reason = "、".join(news_reasons[:2]) if news_reasons else "暂未确认。"

                    self.anomalies.append({
                        "type": "公司重要基本面变化",
                        "level": "high" if news_score >= 75 or news_score <= 25 else "medium",
                        "code": stock.get("code", ""),
                        "name": stock.get("name", ""),
                        "news_score": news_score,
                        "news_level": news_level,
                        "direction": direction,
                        "reason": reason,
                        "description": f"{stock.get('name', '')}消息面{direction}，评分{news_score}分",
                    })
                    logger.info(f"基本面变化: {stock.get('name')} {direction} {news_score}分")

                if len([a for a in self.anomalies if a["type"] == "公司重要基本面变化"]) >= 5:
                    break

        except Exception as e:
            logger.warning(f"检查基本面变化失败: {e}")

    def _generate_summary(self) -> str:
        """生成异动摘要"""
        if not self.anomalies:
            return "盘中无异动，保持静默"

        summary_parts = []
        type_counts = {}
        for anomaly in self.anomalies:
            atype = anomaly["type"]
            if atype not in type_counts:
                type_counts[atype] = 0
            type_counts[atype] += 1

        for atype, count in type_counts.items():
            summary_parts.append(f"{atype}{count}起")

        return "；".join(summary_parts)


# 全局单例
intraday_anomaly_monitor = IntradayAnomalyMonitor()
