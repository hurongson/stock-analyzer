"""
数据采集层：封装 akshare 接口，统一数据格式，带本地缓存
所有方法返回标准化的 pandas DataFrame 或 dict
"""
import time
import logging
import pandas as pd
from typing import Optional, List, Dict, Any
from backend.data.cache import cache
from backend.utils.helpers import normalize_stock_code, retry, today_str

logger = logging.getLogger(__name__)

# 延迟导入 akshare，避免未安装时报错
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    logger.warning("akshare 未安装，数据采集功能不可用")


class DataCollector:
    """A股数据采集器"""

    def __init__(self):
        if not AKSHARE_AVAILABLE:
            raise RuntimeError("akshare 未安装，请运行 pip install akshare")

    # ============ 行情数据 ============

    @retry(max_retries=3, delay=2)
    def get_daily_kline(self, code: str, days: int = 120, adjust: str = "qfq") -> Optional[pd.DataFrame]:
        """
        获取日线K线数据
        :param code: 股票代码
        :param days: 获取天数
        :param adjust: 复权方式 qfq=前复权 hfq=后复权 ""=不复权
        """
        code = normalize_stock_code(code)
        key = f"kline_{code}_{days}_{adjust}"
        cached = cache.get_dataframe("kline", key)
        if cached is not None and not cached.empty:
            return cached

        try:
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=(pd.Timestamp.now() - pd.Timedelta(days=days * 2)).strftime("%Y%m%d"),
                end_date=today_str("%Y%m%d"),
                adjust=adjust
            )
            if df is None or df.empty:
                return None
            # 标准化列名
            df = df.rename(columns={
                "日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume",
                "成交额": "amount", "振幅": "amplitude", "涨跌幅": "pct_change",
                "涨跌额": "change", "换手率": "turnover"
            })
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            df = df.tail(days).reset_index(drop=True)
            cache.set_dataframe("kline", key, df)
            return df
        except Exception as e:
            logger.error(f"获取K线失败 {code}: {e}")
            return None

    @retry(max_retries=2, delay=1)
    def get_realtime_quote(self, code: str) -> Optional[Dict]:
        """获取实时行情快照"""
        code = normalize_stock_code(code)
        key = f"quote_{code}"
        cached = cache.get("quote", key)
        if cached:
            return cached

        try:
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                return None
            row = df[df["代码"] == code]
            if row.empty:
                return None
            r = row.iloc[0]
            result = {
                "code": code,
                "name": r.get("名称", ""),
                "price": float(r.get("最新价", 0)),
                "pct_change": float(r.get("涨跌幅", 0)),
                "change": float(r.get("涨跌额", 0)),
                "volume": float(r.get("成交量", 0)),
                "amount": float(r.get("成交额", 0)),
                "amplitude": float(r.get("振幅", 0)),
                "high": float(r.get("最高", 0)),
                "low": float(r.get("最低", 0)),
                "open": float(r.get("今开", 0)),
                "prev_close": float(r.get("昨收", 0)),
                "turnover": float(r.get("换手率", 0)),
                "pe": float(r.get("市盈率-动态", 0)) if pd.notna(r.get("市盈率-动态")) else None,
                "pb": float(r.get("市净率", 0)) if pd.notna(r.get("市净率")) else None,
                "total_mv": float(r.get("总市值", 0)),
                "circ_mv": float(r.get("流通市值", 0)),
            }
            cache.set("quote", key, result)
            return result
        except Exception as e:
            logger.error(f"获取实时行情失败 {code}: {e}")
            return None

    # ============ 基本面数据 ============

    @retry(max_retries=2, delay=1)
    def get_fundamental(self, code: str) -> Optional[Dict]:
        """获取基本面指标（PE/PB/ROE/营收等）"""
        code = normalize_stock_code(code)
        key = f"fundamental_{code}"
        cached = cache.get("fundamental", key)
        if cached:
            return cached

        result = {}
        try:
            # 主要财务指标
            df = ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")
            if df is not None and not df.empty:
                latest = df.iloc[0]
                result["report_date"] = str(latest.get("报告期", ""))
                result["revenue"] = float(latest.get("营业总收入", 0)) if pd.notna(latest.get("营业总收入")) else None
                result["net_profit"] = float(latest.get("净利润", 0)) if pd.notna(latest.get("净利润")) else None
                result["roe"] = float(latest.get("净资产收益率", 0)) if pd.notna(latest.get("净资产收益率")) else None
                result["gross_margin"] = float(latest.get("销售毛利率", 0)) if pd.notna(latest.get("销售毛利率")) else None
                result["revenue_yoy"] = float(latest.get("营业总收入同比增长率", 0)) if pd.notna(latest.get("营业总收入同比增长率")) else None
                result["profit_yoy"] = float(latest.get("净利润同比增长率", 0)) if pd.notna(latest.get("净利润同比增长率")) else None
        except Exception as e:
            logger.warning(f"获取财务摘要失败 {code}: {e}")

        # 补充实时行情中的 PE/PB
        quote = self.get_realtime_quote(code)
        if quote:
            result["pe"] = quote.get("pe")
            result["pb"] = quote.get("pb")
            result["total_mv"] = quote.get("total_mv")
            result["name"] = quote.get("name")

        if result:
            cache.set("fundamental", key, result)
        return result if result else None

    # ============ 资金流向数据 ============

    @retry(max_retries=2, delay=1)
    def get_capital_flow(self, code: str) -> Optional[Dict]:
        """获取个股资金流向（主力/超大单/大单/中单/小单）"""
        code = normalize_stock_code(code)
        key = f"capital_{code}"
        cached = cache.get("capital", key)
        if cached:
            return cached

        try:
            df = ak.stock_individual_fund_flow(stock=code, market="sh" if code.startswith("6") else "sz")
            if df is None or df.empty:
                return None
            latest = df.iloc[-1]
            result = {
                "date": str(latest.get("日期", "")),
                "main_net_inflow": float(latest.get("主力净流入-净额", 0)),
                "main_net_pct": float(latest.get("主力净流入-净占比", 0)),
                "super_large_net": float(latest.get("超大单净流入-净额", 0)),
                "large_net": float(latest.get("大单净流入-净额", 0)),
                "medium_net": float(latest.get("中单净流入-净额", 0)),
                "small_net": float(latest.get("小单净流入-净额", 0)),
            }
            # 近5日主力净流入
            recent = df.tail(5)
            result["main_net_inflow_5d"] = float(recent["主力净流入-净额"].sum()) if "主力净流入-净额" in recent.columns else None
            cache.set("capital", key, result)
            return result
        except Exception as e:
            logger.warning(f"获取资金流向失败 {code}: {e}")
            return None

    # ============ 概念板块 ============

    @retry(max_retries=2, delay=1)
    def get_stock_concepts(self, code: str) -> Optional[List[str]]:
        """获取个股所属概念板块"""
        code = normalize_stock_code(code)
        key = f"concept_{code}"
        cached = cache.get("concept", key)
        if cached:
            return cached

        try:
            df = ak.stock_board_concept_name_em()
            if df is None or df.empty:
                return None
            # 这个接口返回所有概念板块，需要逐个查成分股，效率低
            # 改用个股详情接口
            try:
                detail = ak.stock_individual_info_em(symbol=code)
                if detail is not None and not detail.empty:
                    industry_row = detail[detail["item"] == "行业"]
                    if not industry_row.empty:
                        concepts = [industry_row.iloc[0]["value"]]
                        cache.set("concept", key, concepts)
                        return concepts
            except Exception:
                pass
            return None
        except Exception as e:
            logger.warning(f"获取概念板块失败 {code}: {e}")
            return None

    @retry(max_retries=2, delay=1)
    def get_hot_concepts(self, top_n: int = 20) -> Optional[pd.DataFrame]:
        """获取热门概念板块涨幅榜"""
        key = f"hot_concepts_{top_n}"
        cached = cache.get_dataframe("concept", key)
        if cached is not None and not cached.empty:
            return cached

        try:
            df = ak.stock_board_concept_name_em()
            if df is None or df.empty:
                return None
            df = df.rename(columns={
                "板块名称": "name", "板块代码": "code", "最新价": "price",
                "涨跌幅": "pct_change", "总市值": "total_mv",
                "换手率": "turnover", "上涨家数": "up_count", "下跌家数": "down_count",
                "领涨股票": "leading_stock", "领涨股票-涨跌幅": "leading_pct"
            })
            df = df.sort_values("pct_change", ascending=False).head(top_n).reset_index(drop=True)
            cache.set_dataframe("concept", key, df)
            return df
        except Exception as e:
            logger.error(f"获取热门概念失败: {e}")
            return None

    # ============ 股票列表 ============

    @retry(max_retries=2, delay=2)
    def get_all_stocks(self) -> Optional[pd.DataFrame]:
        """获取全部A股列表（用于选股）"""
        key = "all_stocks"
        cached = cache.get_dataframe("stock_list", key)
        if cached is not None and not cached.empty:
            return cached

        try:
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                return None
            df = df.rename(columns={
                "序号": "idx", "代码": "code", "名称": "name",
                "最新价": "price", "涨跌幅": "pct_change", "涨跌额": "change",
                "成交量": "volume", "成交额": "amount", "振幅": "amplitude",
                "最高": "high", "最低": "low", "今开": "open", "昨收": "prev_close",
                "换手率": "turnover", "市盈率-动态": "pe", "市净率": "pb",
                "总市值": "total_mv", "流通市值": "circ_mv"
            })
            # 过滤 ST、退市股
            df = df[~df["name"].str.contains("ST|退", na=False)].reset_index(drop=True)
            cache.set_dataframe("stock_list", key, df)
            return df
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            return None

    # ============ 股票名称 ============

    def get_stock_name(self, code: str) -> str:
        """获取股票名称"""
        code = normalize_stock_code(code)
        quote = self.get_realtime_quote(code)
        if quote and quote.get("name"):
            return quote["name"]
        return code


# 全局单例
collector = DataCollector()
