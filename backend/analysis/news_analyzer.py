"""
新闻资讯分析模块
获取财经新闻、政策消息、行业动态，分析对股票的影响
"""
import logging
import re
from typing import List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

# 延迟导入 akshare
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    logger.info("akshare 未安装")


class NewsAnalyzer:
    """新闻资讯分析器"""

    def __init__(self):
        self.news_cache = None
        self.cache_time = None
        self._stock_news_cache = {}

    def get_latest_news(self, limit: int = 30) -> List[Dict]:
        """获取最新财经新闻（财联社全球资讯）"""
        if self.news_cache and self.cache_time and \
           (datetime.now() - self.cache_time).total_seconds() < 600:
            return self.news_cache[:limit]

        news_list = []
        if AKSHARE_AVAILABLE:
            try:
                df = ak.stock_info_global_cls(symbol="全部")
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        title = str(row.get("标题", "")).strip()
                        if not title or title == "nan" or re.match(r'^\d{2}:\d{2}:\d{2}$', title):
                            continue
                        news_list.append({
                            "title": title,
                            "time": str(row.get("发布时间", "")),
                            "source": "财联社",
                        })
                    logger.info(f"财联社获取新闻 {len(news_list)} 条")
            except Exception as e:
                logger.warning(f"财联社新闻获取失败: {str(e)[:80]}")

        self.news_cache = news_list
        self.cache_time = datetime.now()
        return news_list[:limit]

    def analyze_stock_news(self, code: str, name: str) -> Dict:
        """分析个股相关新闻（带1小时缓存）"""
        result = {
            "has_news": False,
            "news_count": 0,
            "positive_count": 0,
            "negative_count": 0,
            "news_list": [],
            "sentiment_score": 50,
        }

        if not AKSHARE_AVAILABLE:
            return result

        # 检查缓存
        cache_key = f"stock_news_{code}"
        if cache_key in self._stock_news_cache:
            cached = self._stock_news_cache[cache_key]
            if (datetime.now() - cached["time"]).total_seconds() < 3600:
                return cached["data"]

        try:
            df = ak.stock_news_em(symbol=code)
            if df is None or df.empty:
                return result

            news_list = []
            positive_keywords = ["增长", "上涨", "利好", "突破", "中标", "签约", "回购", "增持", "业绩预增", "扭亏", "获批", "投产", "合作", "订单", "盈利"]
            negative_keywords = ["下跌", "利空", "亏损", "减持", "违规", "处罚", "退市", "风险", "预警", "下降", "诉讼", "仲裁", "质押", "平仓", "负债"]

            for _, row in df.head(5).iterrows():
                title = str(row.get("新闻标题", "")).strip()
                if not title or title == "nan":
                    continue
                time = str(row.get("发布时间", ""))
                try:
                    news_time = datetime.strptime(time[:10], "%Y-%m-%d")
                    if (datetime.now() - news_time).days > 7:
                        continue
                except Exception:
                    pass

                sentiment = "neutral"
                if any(kw in title for kw in positive_keywords):
                    sentiment = "positive"
                    result["positive_count"] += 1
                elif any(kw in title for kw in negative_keywords):
                    sentiment = "negative"
                    result["negative_count"] += 1

                news_list.append({
                    "title": title,
                    "time": time,
                    "sentiment": sentiment,
                })

            result["has_news"] = len(news_list) > 0
            result["news_count"] = len(news_list)
            result["news_list"] = news_list[:3]

            if result["news_count"] > 0:
                pos_ratio = result["positive_count"] / result["news_count"]
                neg_ratio = result["negative_count"] / result["news_count"]
                result["sentiment_score"] = round(50 + pos_ratio * 30 - neg_ratio * 30)
                result["sentiment_score"] = max(0, min(100, result["sentiment_score"]))

            # 保存到缓存
            self._stock_news_cache[cache_key] = {
                "time": datetime.now(),
                "data": result,
            }

        except Exception as e:
            logger.debug(f"获取 {code} 新闻失败: {str(e)[:80]}")

        return result

    def get_news_impact_score(self, code: str, name: str) -> Dict:
        """获取股票的消息面影响评分"""
        result = {
            "score": 50,
            "level": "中性",
            "reasons": [],
            "has_positive_news": False,
            "has_negative_news": False,
        }

        stock_news = self.analyze_stock_news(code, name)
        if stock_news["has_news"]:
            result["score"] = stock_news["sentiment_score"]
            if stock_news["positive_count"] > 0:
                result["has_positive_news"] = True
                result["reasons"].append(f"近期{stock_news['positive_count']}条正面新闻")
            if stock_news["negative_count"] > 0:
                result["has_negative_news"] = True
                result["reasons"].append(f"近期{stock_news['negative_count']}条负面新闻")

        if result["score"] >= 70:
            result["level"] = "利好"
        elif result["score"] >= 60:
            result["level"] = "偏利好"
        elif result["score"] <= 30:
            result["level"] = "利空"
        elif result["score"] <= 40:
            result["level"] = "偏利空"

        return result


# 全局单例
news_analyzer = NewsAnalyzer()
