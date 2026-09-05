"""
盘后市场变化分析模块（表3）
不重复指数涨跌和普通行情摘要
重点比较今天与过去1日、5日的变化
输出：
- 市场3大变化
- 板块状态变化TOP5
- 公司基本面变化TOP10
- 重大公告TOP10
"""

import logging
from typing import Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)


class MarketChangeAnalyzer:
    """盘后市场变化分析器"""

    def __init__(self):
        pass

    def analyze_market_changes(self, today_data: Dict, history_data: Dict) -> Dict:
        """
        分析盘后市场变化
        today_data: 今天的市场数据
        history_data: 历史数据（1日前、5日前）
        """
        result = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "market_3_changes": [],
            "sector_changes_top5": [],
            "company_fundamental_changes_top10": [],
            "major_announcements_top10": [],
        }

        # 1. 市场3大变化
        result["market_3_changes"] = self._analyze_market_3_changes(today_data, history_data)

        # 2. 板块状态变化TOP5
        result["sector_changes_top5"] = self._analyze_sector_changes(today_data, history_data)

        # 3. 公司基本面变化TOP10
        result["company_fundamental_changes_top10"] = self._analyze_company_fundamental_changes(today_data)

        # 4. 重大公告TOP10
        result["major_announcements_top10"] = self._analyze_major_announcements(today_data)

        return result

    def _analyze_market_3_changes(self, today_data: Dict, history_data: Dict) -> List[Dict]:
        """分析市场3大变化"""
        changes = []

        try:
            # 变化1：市场情绪变化（涨跌比、涨停数、跌停数）
            today_up = today_data.get("up_count", 0)
            today_down = today_data.get("down_count", 0)
            today_limit_up = today_data.get("limit_up_count", 0)
            today_limit_down = today_data.get("limit_down_count", 0)

            history_1d = history_data.get("1_day_ago", {})
            history_5d = history_data.get("5_days_ago", {})

            prev_up = history_1d.get("up_count", today_up)
            prev_down = history_1d.get("down_count", today_down)
            prev_limit_up = history_1d.get("limit_up_count", today_limit_up)

            up_ratio_change = 0
            if prev_up + prev_down > 0:
                today_ratio = today_up / (today_up + today_down) if (today_up + today_down) > 0 else 0.5
                prev_ratio = prev_up / (prev_up + prev_down)
                up_ratio_change = (today_ratio - prev_ratio) * 100

            limit_up_change = today_limit_up - prev_limit_up

            if abs(up_ratio_change) > 10 or abs(limit_up_change) > 10:
                direction = "转强" if up_ratio_change > 0 else "转弱"
                changes.append({
                    "rank": 1,
                    "title": f"市场情绪{direction}",
                    "description": f"涨跌比变化{up_ratio_change:+.1f}%，涨停数变化{limit_up_change:+d}只",
                    "comparison": f"今日上涨{today_up}只/下跌{today_down}只，涨停{today_limit_up}只；昨日上涨{prev_up}只/下跌{prev_down}只，涨停{prev_limit_up}只",
                    "impact": "high" if abs(up_ratio_change) > 20 else "medium",
                })

            # 变化2：成交量变化
            today_volume = today_data.get("total_volume", 0)
            prev_volume = history_1d.get("total_volume", today_volume)
            volume_change = ((today_volume - prev_volume) / prev_volume * 100) if prev_volume > 0 else 0

            if abs(volume_change) > 20:
                direction = "放量" if volume_change > 0 else "缩量"
                changes.append({
                    "rank": len(changes) + 1,
                    "title": f"市场{direction}",
                    "description": f"成交量变化{volume_change:+.1f}%",
                    "comparison": f"今日成交{today_volume/100000000:.0f}亿，昨日{prev_volume/100000000:.0f}亿",
                    "impact": "high" if abs(volume_change) > 30 else "medium",
                })

            # 变化3：风格切换（大盘股vs小盘股）
            large_cap_pct = today_data.get("large_cap_avg_pct", 0)
            small_cap_pct = today_data.get("small_cap_avg_pct", 0)
            style_diff = large_cap_pct - small_cap_pct

            prev_large = history_1d.get("large_cap_avg_pct", large_cap_pct)
            prev_small = history_1d.get("small_cap_avg_pct", small_cap_pct)
            prev_style_diff = prev_large - prev_small

            style_change = style_diff - prev_style_diff

            if abs(style_change) > 1:
                direction = "大盘股强于小盘股" if style_change > 0 else "小盘股强于大盘股"
                changes.append({
                    "rank": len(changes) + 1,
                    "title": f"市场风格切换：{direction}",
                    "description": f"大小盘涨幅差变化{style_change:+.1f}%",
                    "comparison": f"今日大盘股{large_cap_pct:+.1f}%/小盘股{small_cap_pct:+.1f}%；昨日大盘股{prev_large:+.1f}%/小盘股{prev_small:+.1f}%",
                    "impact": "medium",
                })

            # 如果不足3个变化，补充通用分析
            while len(changes) < 3:
                rank = len(changes) + 1
                if rank == 1:
                    changes.append({
                        "rank": rank,
                        "title": "市场整体平稳",
                        "description": "主要指标变化不大，市场处于震荡格局",
                        "comparison": "涨跌比、成交量、风格切换均无显著变化",
                        "impact": "low",
                    })
                elif rank == 2:
                    changes.append({
                        "rank": rank,
                        "title": "板块轮动加速",
                        "description": "热点板块切换频繁，持续性有待观察",
                        "comparison": "建议关注板块轮动节奏，避免追高",
                        "impact": "medium",
                    })
                else:
                    changes.append({
                        "rank": rank,
                        "title": "资金面偏谨慎",
                        "description": "市场观望情绪较浓，等待明确方向",
                        "comparison": "建议控制仓位，等待市场企稳",
                        "impact": "medium",
                    })

        except Exception as e:
            logger.warning(f"分析市场3大变化失败: {e}")
            changes = [
                {"rank": 1, "title": "市场分析暂未确认", "description": "数据获取异常，暂无法分析", "impact": "low"},
            ]

        return changes[:3]

    def _analyze_sector_changes(self, today_data: Dict, history_data: Dict) -> List[Dict]:
        """分析板块状态变化TOP5"""
        sector_changes = []

        try:
            today_sectors = today_data.get("sectors", {})
            history_sectors = history_data.get("1_day_ago", {}).get("sectors", {})

            # 计算各板块变化
            for sector, today_info in today_sectors.items():
                today_pct = today_info.get("avg_pct", 0)
                today_count = today_info.get("stock_count", 0)
                prev_info = history_sectors.get(sector, {})
                prev_pct = prev_info.get("avg_pct", 0)

                change = today_pct - prev_pct
                sector_changes.append({
                    "sector": sector,
                    "today_pct": round(today_pct, 2),
                    "prev_pct": round(prev_pct, 2),
                    "change": round(change, 2),
                    "stock_count": today_count,
                    "status": "转强" if change > 1 else ("转弱" if change < -1 else "平稳"),
                })

            # 按变化幅度排序
            sector_changes.sort(key=lambda x: abs(x["change"]), reverse=True)

            # 取TOP5
            for i, sc in enumerate(sector_changes[:5]):
                sc["rank"] = i + 1

        except Exception as e:
            logger.warning(f"分析板块变化失败: {e}")

        return sector_changes[:5]

    def _analyze_company_fundamental_changes(self, today_data: Dict) -> List[Dict]:
        """分析公司基本面变化TOP10"""
        fundamental_changes = []

        try:
            stocks = today_data.get("stocks", [])

            for stock in stocks:
                news_impact = stock.get("news_impact", {})
                news_score = news_impact.get("score", 50)
                news_level = news_impact.get("level", "中性")
                news_reasons = news_impact.get("reasons", [])

                # 筛选有显著基本面变化的股票
                if news_score >= 65 or news_score <= 35:
                    direction = "利好" if news_score >= 65 else "利空"
                    fundamental_changes.append({
                        "code": stock.get("code", ""),
                        "name": stock.get("name", ""),
                        "price": stock.get("price", 0),
                        "pct_change": stock.get("pct_change", 0),
                        "news_score": news_score,
                        "news_level": news_level,
                        "direction": direction,
                        "reasons": news_reasons[:3],
                        "change_description": "、".join(news_reasons[:2]) if news_reasons else "暂未确认。",
                    })

            # 按消息面评分变化幅度排序
            fundamental_changes.sort(key=lambda x: abs(x["news_score"] - 50), reverse=True)

            # 取TOP10并添加排名
            for i, fc in enumerate(fundamental_changes[:10]):
                fc["rank"] = i + 1

        except Exception as e:
            logger.warning(f"分析公司基本面变化失败: {e}")

        return fundamental_changes[:10]

    def _analyze_major_announcements(self, today_data: Dict) -> List[Dict]:
        """分析重大公告TOP10"""
        announcements = []

        try:
            raw_announcements = today_data.get("announcements", [])

            # 筛选重要公告
            keywords = ["业绩预增", "业绩预告", "重大合同", "中标", "订单", "涨价", "提价",
                        "回购", "增持", "新产品", "合作", "签约", "资产重组", "股权激励"]

            for ann in raw_announcements:
                title = ann.get("title", "")
                if any(kw in title for kw in keywords):
                    announcements.append({
                        "code": ann.get("code", ""),
                        "name": ann.get("name", ""),
                        "title": title,
                        "date": ann.get("date", ""),
                        "type": self._classify_announcement(title),
                        "importance": "high" if any(kw in title for kw in ["重大合同", "中标", "业绩预增", "资产重组"]) else "medium",
                    })

            # 按重要性排序
            announcements.sort(key=lambda x: 0 if x["importance"] == "high" else 1)

            # 取TOP10并添加排名
            for i, ann in enumerate(announcements[:10]):
                ann["rank"] = i + 1

        except Exception as e:
            logger.warning(f"分析重大公告失败: {e}")

        return announcements[:10]

    def _classify_announcement(self, title: str) -> str:
        """分类公告类型"""
        if any(kw in title for kw in ["业绩预增", "业绩预告", "业绩"]):
            return "业绩变化"
        elif any(kw in title for kw in ["重大合同", "中标", "订单"]):
            return "重大订单"
        elif any(kw in title for kw in ["涨价", "提价"]):
            return "产品涨价"
        elif any(kw in title for kw in ["回购", "增持"]):
            return "回购增持"
        elif any(kw in title for kw in ["新产品", "合作", "签约"]):
            return "业务进展"
        elif any(kw in title for kw in ["资产重组", "并购"]):
            return "资产重组"
        else:
            return "其他重要公告"


# 全局单例
market_change_analyzer = MarketChangeAnalyzer()
