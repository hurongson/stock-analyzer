"""
数据采集层：Tushare 优先 + akshare 备用，统一数据格式，带本地缓存
所有方法返回标准化的 pandas DataFrame 或 dict
"""
import os
import json
import time
import logging
import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any
from backend.data.cache import cache
from backend.utils.helpers import normalize_stock_code, retry, today_str
from backend.config import Config

logger = logging.getLogger(__name__)

# ============ 延迟导入数据源 ============
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    logger.info("akshare 未安装")

try:
    import tushare as ts
    if Config.TUSHARE_TOKEN:
        ts.set_token(Config.TUSHARE_TOKEN)
        pro = ts.pro_api()
        TUSHARE_AVAILABLE = True
        logger.info("Tushare 已初始化")
    else:
        TUSHARE_AVAILABLE = False
        pro = None
        logger.info("Tushare 未配置 token")
except ImportError:
    TUSHARE_AVAILABLE = False
    pro = None
    logger.info("tushare 未安装")


# ============ 工具函数 ============
def to_ts_code(code: str) -> str:
    """股票代码转 Tushare 格式：600519 → 600519.SH"""
    code = normalize_stock_code(code)
    if code.startswith(("60", "68", "90")):
        return f"{code}.SH"
    elif code.startswith(("00", "30", "20")):
        return f"{code}.SZ"
    elif code.startswith(("43", "83", "87", "88", "92")):
        return f"{code}.BJ"
    return f"{code}.SH"


def from_ts_code(ts_code: str) -> str:
    """Tushare 代码转纯数字：600519.SH → 600519"""
    return ts_code.split(".")[0]


def safe_float(val, default=None):
    """安全转换 float，处理带单位的字符串（亿/万/%）"""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s in ("-", "--", "None", "nan"):
        return default
    try:
        multiplier = 1.0
        if "亿" in s:
            multiplier = 1e8
            s = s.replace("亿", "")
        elif "万" in s:
            multiplier = 1e4
            s = s.replace("万", "")
        if "%" in s:
            s = s.replace("%", "")
        return float(s) * multiplier
    except (ValueError, TypeError):
        return default


def get_latest_trade_date() -> str:
    """获取最近交易日（Tushare 格式 YYYYMMDD）"""
    if TUSHARE_AVAILABLE:
        try:
            df = pro.trade_cal(exchange='SSE', start_date=(pd.Timestamp.now() - pd.Timedelta(days=10)).strftime("%Y%m%d"),
                               end_date=today_str("%Y%m%d"), is_open='1')
            if df is not None and not df.empty:
                return df.iloc[-1]["cal_date"]
        except Exception as e:
            logger.debug(f"获取交易日历失败: {e}")
    # fallback：简单判断，周末回退
    d = pd.Timestamp.now()
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d.strftime("%Y%m%d")


class DataCollector:
    """A股数据采集器：Tushare 优先，akshare 备用"""

    def __init__(self):
        if not TUSHARE_AVAILABLE and not AKSHARE_AVAILABLE:
            raise RuntimeError("Tushare 和 akshare 均未安装/配置")
        self._latest_trade_date = None

    @property
    def latest_trade_date(self):
        if self._latest_trade_date is None:
            self._latest_trade_date = get_latest_trade_date()
        return self._latest_trade_date

    # ============ 日线K线 ============
    def get_daily_kline(self, code: str, days: int = 120, adjust: str = "qfq") -> Optional[pd.DataFrame]:
        code = normalize_stock_code(code)
        key = f"kline_{code}_{days}_{adjust}"
        cached = cache.get_dataframe("kline", key)
        if cached is not None and not cached.empty:
            return cached

        # 优先 Tushare
        if TUSHARE_AVAILABLE:
            try:
                ts_code = to_ts_code(code)
                start = (pd.Timestamp.now() - pd.Timedelta(days=days * 2)).strftime("%Y%m%d")
                df = pro.daily(ts_code=ts_code, start_date=start, end_date=today_str("%Y%m%d"))
                if df is not None and not df.empty:
                    df = df.rename(columns={
                        "trade_date": "date", "vol": "volume", "pct_chg": "pct_change"
                    })
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.sort_values("date").reset_index(drop=True)
                    # Tushare vol 单位是手，转成股
                    df["volume"] = df["volume"] * 100
                    df = df.tail(days).reset_index(drop=True)
                    # 确保列存在
                    for col in ["open", "high", "low", "close", "volume", "amount", "pct_change", "change"]:
                        if col not in df.columns:
                            df[col] = 0
                    cache.set_dataframe("kline", key, df)
                    return df
            except Exception as e:
                logger.warning(f"Tushare 获取K线失败 {code}: {e}")

        # fallback akshare
        if AKSHARE_AVAILABLE:
            try:
                df = ak.stock_zh_a_hist(
                    symbol=code, period="daily",
                    start_date=(pd.Timestamp.now() - pd.Timedelta(days=days * 2)).strftime("%Y%m%d"),
                    end_date=today_str("%Y%m%d"), adjust=adjust
                )
                if df is None or df.empty:
                    return None
                df = df.rename(columns={
                    "日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
                    "成交量": "volume", "成交额": "amount", "振幅": "amplitude",
                    "涨跌幅": "pct_change", "涨跌额": "change", "换手率": "turnover"
                })
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
                df = df.tail(days).reset_index(drop=True)
                cache.set_dataframe("kline", key, df)
                return df
            except Exception as e:
                logger.error(f"akshare 获取K线失败 {code}: {e}")

        return None

    # ============ 实时/最新行情 ============
    # 常见股票名称映射（stock_basic 接口频率受限，用此兜底）
    DEFAULT_STOCK_NAME_MAP = {
        "600519": "贵州茅台", "000001": "平安银行", "300750": "宁德时代",
        "002594": "比亚迪", "601318": "中国平安", "600036": "招商银行",
        "000858": "五粮液", "601899": "紫金矿业", "600900": "长江电力",
        "000333": "美的集团", "601166": "兴业银行", "600276": "恒瑞医药",
        "002415": "海康威视", "601012": "隆基绿能", "300059": "东方财富",
        "600030": "中信证券", "000725": "京东方A", "601888": "中国中免",
        "600887": "伊利股份", "000568": "泸州老窖", "002475": "立讯精密",
        "600309": "万华化学", "601668": "中国建筑", "601398": "工商银行",
    }

    def __init__(self):
        self._latest_trade_date = None
        ts_status = "可用" if TUSHARE_AVAILABLE else "未配置"
        ak_status = "可用" if AKSHARE_AVAILABLE else "未安装"
        logger.info(f"数据源状态: Tushare={ts_status}, akshare={ak_status}")
        # 加载外部股票名称映射表（如果存在）
        self.STOCK_NAME_MAP = dict(self.DEFAULT_STOCK_NAME_MAP)
        map_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stock_name_map.json")
        if os.path.exists(map_path):
            try:
                with open(map_path, "r", encoding="utf-8") as f:
                    external_map = json.load(f)
                self.STOCK_NAME_MAP.update(external_map)
                logger.info(f"加载外部股票名称映射表: {len(external_map)} 只")
            except Exception as e:
                logger.warning(f"加载股票名称映射表失败: {e}")

    def get_realtime_quote(self, code: str) -> Optional[Dict]:
        code = normalize_stock_code(code)
        key = f"quote_{code}"
        cached = cache.get("quote", key)
        if cached:
            return cached

        # 优先 Tushare：从K线最新数据获取价格（不依赖频率受限的 stock_basic/daily_basic）
        if TUSHARE_AVAILABLE:
            try:
                kline = self.get_daily_kline(code, days=10)
                if kline is not None and not kline.empty:
                    latest = kline.iloc[-1]
                    prev = kline.iloc[-2] if len(kline) >= 2 else None
                    price = safe_float(latest.get("close"), 0)
                    prev_close = safe_float(latest.get("prev_close"), safe_float(prev.get("close") if prev is not None else 0, 0))
                    change = price - prev_close if prev_close else 0
                    pct_change = (change / prev_close * 100) if prev_close else 0

                    result = {
                        "code": code,
                        "name": self.STOCK_NAME_MAP.get(code, code),
                        "price": price,
                        "pct_change": round(pct_change, 2),
                        "change": round(change, 2),
                        "volume": safe_float(latest.get("volume"), 0),
                        "amount": safe_float(latest.get("amount"), 0),
                        "high": safe_float(latest.get("high"), 0),
                        "low": safe_float(latest.get("low"), 0),
                        "open": safe_float(latest.get("open"), 0),
                        "prev_close": prev_close,
                        "turnover": safe_float(latest.get("turnover"), 0),
                        "pe": None,
                        "pb": None,
                        "total_mv": 0,
                        "circ_mv": 0,
                    }
                    cache.set("quote", key, result)
                    return result
            except Exception as e:
                logger.debug(f"Tushare 获取行情失败 {code}: {e}")

        # fallback akshare
        if AKSHARE_AVAILABLE:
            try:
                df = ak.stock_zh_a_spot_em()
                if df is None or df.empty:
                    return None
                row = df[df["代码"] == code]
                if row.empty:
                    return None
                r = row.iloc[0]
                result = {
                    "code": code, "name": r.get("名称", ""),
                    "price": safe_float(r.get("最新价"), 0),
                    "pct_change": safe_float(r.get("涨跌幅"), 0),
                    "change": safe_float(r.get("涨跌额"), 0),
                    "volume": safe_float(r.get("成交量"), 0),
                    "amount": safe_float(r.get("成交额"), 0),
                    "amplitude": safe_float(r.get("振幅"), 0),
                    "high": safe_float(r.get("最高"), 0),
                    "low": safe_float(r.get("最低"), 0),
                    "open": safe_float(r.get("今开"), 0),
                    "prev_close": safe_float(r.get("昨收"), 0),
                    "turnover": safe_float(r.get("换手率"), 0),
                    "pe": safe_float(r.get("市盈率-动态")),
                    "pb": safe_float(r.get("市净率")),
                    "total_mv": safe_float(r.get("总市值"), 0),
                    "circ_mv": safe_float(r.get("流通市值"), 0),
                }
                cache.set("quote", key, result)
                return result
            except Exception as e:
                logger.error(f"akshare 获取行情失败 {code}: {e}")
        return None

    def get_turnover_rate(self, code: str, trade_date: str = None) -> Optional[Dict]:
        """获取股票换手率（使用Tushare daily_basic接口，GitHub Actions环境可用）"""
        code = normalize_stock_code(code)
        key = f"turnover_{code}_{trade_date or 'latest'}"
        cached = cache.get("turnover", key)
        if cached:
            return cached

        result = {}
        if TUSHARE_AVAILABLE:
            try:
                ts_code = to_ts_code(code)
                params = {"ts_code": ts_code, "fields": "ts_code,trade_date,turnover_rate,turnover_rate_f,volume_ratio"}
                if trade_date:
                    params["trade_date"] = trade_date
                df = pro.daily_basic(**params)
                if df is not None and not df.empty:
                    latest = df.iloc[0]
                    result = {
                        "turnover_rate": safe_float(latest.get("turnover_rate"), 0),
                        "turnover_rate_f": safe_float(latest.get("turnover_rate_f"), 0),
                        "volume_ratio": safe_float(latest.get("volume_ratio"), 0),
                        "trade_date": str(latest.get("trade_date", "")),
                    }
                    cache.set("turnover", key, result)
                    return result
            except Exception as e:
                logger.debug(f"Tushare 获取换手率失败 {code}: {e}")
        return None

    # ============ 基本面 ============
    def get_fundamental(self, code: str) -> Optional[Dict]:
        code = normalize_stock_code(code)
        key = f"fundamental_{code}"
        cached = cache.get("fundamental", key)
        if cached:
            return cached

        result = {}

        # 优先 Tushare
        if TUSHARE_AVAILABLE:
            try:
                ts_code = to_ts_code(code)
                # 财务指标
                fina_df = pro.fina_indicator(ts_code=ts_code,
                    fields='ts_code,end_date,roe,roe_waa,grossprofit_margin,netprofit_margin,or_yoy,netprofit_yoy,eps,dt_eps')
                if fina_df is not None and not fina_df.empty:
                    latest = fina_df.iloc[0]
                    result.update({
                        "report_date": str(latest.get("end_date", "")),
                        "roe": safe_float(latest.get("roe")),
                        "gross_margin": safe_float(latest.get("grossprofit_margin")),
                        "revenue_yoy": safe_float(latest.get("or_yoy")),
                        "profit_yoy": safe_float(latest.get("netprofit_yoy")),
                        "eps": safe_float(latest.get("eps")),
                    })
                # 利润表（营收/净利润绝对值）
                income_df = pro.income(ts_code=ts_code,
                    fields='ts_code,end_date,total_revenue,n_income')
                if income_df is not None and not income_df.empty:
                    latest = income_df.iloc[0]
                    result["revenue"] = safe_float(latest.get("total_revenue"))
                    result["net_profit"] = safe_float(latest.get("n_income"))
            except Exception as e:
                logger.debug(f"Tushare 获取基本面失败 {code}: {e}")

        # fallback akshare 财务摘要
        if AKSHARE_AVAILABLE and not result:
            try:
                df = ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")
                if df is not None and not df.empty:
                    latest = df.iloc[0]
                    result.update({
                        "report_date": str(latest.get("报告期", "")),
                        "revenue": safe_float(latest.get("营业总收入")),
                        "net_profit": safe_float(latest.get("净利润")),
                        "roe": safe_float(latest.get("净资产收益率")),
                        "gross_margin": safe_float(latest.get("销售毛利率")),
                        "revenue_yoy": safe_float(latest.get("营业总收入同比增长率")),
                        "profit_yoy": safe_float(latest.get("净利润同比增长率")),
                    })
            except Exception as e:
                logger.warning(f"akshare 获取财务摘要失败 {code}: {e}")

        # 补充行情中的 PE/PB/市值/名称
        quote = self.get_realtime_quote(code)
        if quote:
            result["pe"] = quote.get("pe")
            result["pb"] = quote.get("pb")
            result["total_mv"] = quote.get("total_mv")
            result["name"] = quote.get("name")

        if result:
            cache.set("fundamental", key, result)
        return result if result else None

    # ============ 资金流向 ============
    def get_capital_flow(self, code: str) -> Optional[Dict]:
        code = normalize_stock_code(code)
        key = f"capital_{code}"
        cached = cache.get("capital", key)
        if cached:
            return cached

        # 优先 Tushare
        if TUSHARE_AVAILABLE:
            try:
                ts_code = to_ts_code(code)
                trade_date = self.latest_trade_date
                df = pro.moneyflow(ts_code=ts_code, start_date=(pd.Timestamp.now() - pd.Timedelta(days=10)).strftime("%Y%m%d"),
                                   end_date=today_str("%Y%m%d"))
                if df is not None and not df.empty:
                    df = df.sort_values("trade_date").reset_index(drop=True)
                    latest = df.iloc[-1]
                    # Tushare moneyflow 字段：
                    # buy_sm_vol/amount, sell_sm_vol/amount (小单)
                    # buy_md_vol/amount, sell_md_vol/amount (中单)
                    # buy_lg_vol/amount, sell_lg_vol/amount (大单)
                    # buy_elg_vol/amount, sell_elg_vol/amount (超大单)
                    # net_mf_vol, net_mf_amount (主力净流入)
                    super_large_net = safe_float(latest.get("buy_elg_amount"), 0) - safe_float(latest.get("sell_elg_amount"), 0)
                    large_net = safe_float(latest.get("buy_lg_amount"), 0) - safe_float(latest.get("sell_lg_amount"), 0)
                    medium_net = safe_float(latest.get("buy_md_amount"), 0) - safe_float(latest.get("sell_md_amount"), 0)
                    small_net = safe_float(latest.get("buy_sm_amount"), 0) - safe_float(latest.get("sell_sm_amount"), 0)
                    main_net = safe_float(latest.get("net_mf_amount"), 0)
                    # 金额单位：Tushare 是千元，转元
                    main_net *= 1000
                    super_large_net *= 1000
                    large_net *= 1000
                    medium_net *= 1000
                    small_net *= 1000

                    # 计算净占比（需要成交额）
                    quote = self.get_realtime_quote(code)
                    amount = quote.get("amount", 1) if quote else 1
                    main_pct = (main_net / amount * 100) if amount else 0

                    # 近5日主力净流入
                    recent = df.tail(5)
                    main_5d = safe_float(recent["net_mf_amount"].sum(), 0) * 1000 if "net_mf_amount" in recent.columns else None

                    result = {
                        "date": str(latest.get("trade_date", "")),
                        "main_net_inflow": main_net,
                        "main_net_pct": round(main_pct, 2),
                        "super_large_net": super_large_net,
                        "large_net": large_net,
                        "medium_net": medium_net,
                        "small_net": small_net,
                        "main_net_inflow_5d": main_5d,
                    }
                    cache.set("capital", key, result)
                    return result
            except Exception as e:
                logger.debug(f"Tushare 获取资金流向失败 {code}: {e}")

        # fallback akshare
        if AKSHARE_AVAILABLE:
            try:
                df = ak.stock_individual_fund_flow(stock=code, market="sh" if code.startswith("6") else "sz")
                if df is None or df.empty:
                    return None
                latest = df.iloc[-1]
                result = {
                    "date": str(latest.get("日期", "")),
                    "main_net_inflow": safe_float(latest.get("主力净流入-净额"), 0),
                    "main_net_pct": safe_float(latest.get("主力净流入-净占比"), 0),
                    "super_large_net": safe_float(latest.get("超大单净流入-净额"), 0),
                    "large_net": safe_float(latest.get("大单净流入-净额"), 0),
                    "medium_net": safe_float(latest.get("中单净流入-净额"), 0),
                    "small_net": safe_float(latest.get("小单净流入-净额"), 0),
                }
                recent = df.tail(5)
                result["main_net_inflow_5d"] = safe_float(recent["主力净流入-净额"].sum(), 0) if "主力净流入-净额" in recent.columns else None
                cache.set("capital", key, result)
                return result
            except Exception as e:
                logger.warning(f"akshare 获取资金流向失败 {code}: {e}")
        return None

    # ============ 概念板块 ============
    def get_stock_concepts(self, code: str) -> Optional[List[str]]:
        code = normalize_stock_code(code)
        key = f"concept_{code}"
        cached = cache.get("concept", key)
        if cached:
            return cached

        # 优先 Tushare
        if TUSHARE_AVAILABLE:
            try:
                ts_code = to_ts_code(code)
                df = pro.concept_detail(ts_code=ts_code, fields='id,concept_name')
                if df is not None and not df.empty:
                    concepts = df["concept_name"].tolist()
                    # 补充行业
                    try:
                        basic_df = pro.stock_basic(ts_code=ts_code, fields='ts_code,industry')
                        if basic_df is not None and not basic_df.empty:
                            industry = basic_df.iloc[0].get("industry")
                            if industry and industry not in concepts:
                                concepts.insert(0, industry)
                    except Exception:
                        pass
                    cache.set("concept", key, concepts)
                    return concepts
            except Exception as e:
                logger.debug(f"Tushare 获取概念失败 {code}: {e}")

        # fallback akshare
        if AKSHARE_AVAILABLE:
            try:
                detail = ak.stock_individual_info_em(symbol=code)
                if detail is not None and not detail.empty:
                    industry_row = detail[detail["item"] == "行业"]
                    if not industry_row.empty:
                        concepts = [industry_row.iloc[0]["value"]]
                        cache.set("concept", key, concepts)
                        return concepts
            except Exception as e:
                logger.warning(f"akshare 获取概念失败 {code}: {e}")
        return None

    def get_hot_concepts(self, top_n: int = 20) -> Optional[pd.DataFrame]:
        key = f"hot_concepts_{top_n}"
        cached = cache.get_dataframe("concept", key)
        if cached is not None and not cached.empty:
            return cached

        # Tushare 没有直接的概念涨幅榜，用 akshare
        if AKSHARE_AVAILABLE:
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
                logger.error(f"akshare 获取热门概念失败: {e}")
        return None

    # ============ 全量股票列表 ============
    def get_all_stocks(self) -> Optional[pd.DataFrame]:
        key = "all_stocks"
        cached = cache.get_dataframe("stock_list", key)
        if cached is not None and not cached.empty:
            return cached

        # 优先 Tushare：用 daily(trade_date) 获取全量股票日线，不依赖频率受限的 stock_basic
        if TUSHARE_AVAILABLE:
            try:
                # 尝试最近5个交易日（交易时段当日数据可能未更新）
                daily_df = None
                used_date = None
                for days_back in range(5):
                    try:
                        check_date = (pd.Timestamp.now() - pd.Timedelta(days=days_back)).strftime("%Y%m%d")
                        # 跳过周末
                        if pd.Timestamp(check_date).weekday() >= 5:
                            continue
                        daily_df = pro.daily(trade_date=check_date,
                            fields='ts_code,open,high,low,close,pre_close,change,pct_chg,vol,amount')
                        if daily_df is not None and not daily_df.empty:
                            used_date = check_date
                            logger.info(f"Tushare 使用 {used_date} 数据，共 {len(daily_df)} 只股票")
                            break
                    except Exception as e:
                        logger.debug(f"Tushare daily {check_date} 失败: {e}")
                        continue

                if daily_df is None or daily_df.empty:
                    raise ValueError("最近5个交易日 daily 均返回空")

                df = daily_df.copy()
                df["code"] = df["ts_code"].apply(from_ts_code)
                # 股票名称用映射表兜底
                df["name"] = df["code"].apply(lambda c: self.STOCK_NAME_MAP.get(c, c))
                df["price"] = df["close"]
                df["pct_change"] = df["pct_chg"]
                df["volume"] = df["vol"] * 100  # 手→股
                df["amount"] = df["amount"] * 1000  # 千元→元

                # 统一列名（PE/PB/市值等无权限接口，留空）
                for col in ["turnover", "pe", "pb", "total_mv", "circ_mv", "amplitude"]:
                    if col not in df.columns:
                        df[col] = 0

                # 过滤 ST、退市（名称中包含的）
                df = df[~df["name"].str.contains("ST|退", na=False)].reset_index(drop=True)
                cache.set_dataframe("stock_list", key, df)
                return df
            except Exception as e:
                logger.error(f"Tushare 获取股票列表失败: {e}")

        # fallback akshare（带重试，多数据源fallback）
        if AKSHARE_AVAILABLE:
            df = None
            
            # 数据源1: 新浪财经（已验证在GitHub Actions中稳定可用）
            for retry in range(3):
                try:
                    logger.info(f"尝试新浪财经获取股票列表（第{retry+1}次）...")
                    df = ak.stock_zh_a_spot()
                    if df is not None and not df.empty:
                        logger.info(f"新浪财经获取成功，共 {len(df)} 只股票")
                        # 统一列名
                        df = df.rename(columns={
                            "代码": "code", "名称": "name",
                            "最新价": "price", "涨跌幅": "pct_change",
                            "涨跌额": "change", "成交量": "volume",
                            "成交额": "amount", "最高": "high",
                            "最低": "low", "今开": "open", "昨收": "prev_close",
                        })
                        # 新浪财经缺少的列，添加默认值
                        for col in ["turnover", "pe", "pb", "total_mv", "circ_mv", "amplitude"]:
                            if col not in df.columns:
                                df[col] = 0
                        # 计算振幅
                        if "amplitude" in df.columns and "prev_close" in df.columns:
                            mask = df["prev_close"] > 0
                            df.loc[mask, "amplitude"] = (df.loc[mask, "high"] - df.loc[mask, "low"]) / df.loc[mask, "prev_close"] * 100
                        break
                except Exception as e:
                    logger.warning(f"新浪财经获取股票列表第{retry+1}次失败: {str(e)[:80]}")
                    time.sleep(2)
            
            # 数据源2: 东方财富（备用，在GitHub Actions中可能连接失败）
            if df is None or df.empty:
                for retry in range(3):
                    try:
                        logger.info(f"尝试东方财富获取股票列表（第{retry+1}次）...")
                        df = ak.stock_zh_a_spot_em()
                        if df is not None and not df.empty:
                            logger.info(f"东方财富获取成功，共 {len(df)} 只股票")
                            df = df.rename(columns={
                                "序号": "idx", "代码": "code", "名称": "name",
                                "最新价": "price", "涨跌幅": "pct_change", "涨跌额": "change",
                                "成交量": "volume", "成交额": "amount", "振幅": "amplitude",
                                "最高": "high", "最低": "low", "今开": "open", "昨收": "prev_close",
                                "换手率": "turnover", "市盈率-动态": "pe", "市净率": "pb",
                                "总市值": "total_mv", "流通市值": "circ_mv"
                            })
                            break
                    except Exception as e:
                        logger.warning(f"东方财富获取股票列表第{retry+1}次失败: {str(e)[:80]}")
                        time.sleep(2)
            
            if df is None or df.empty:
                logger.error("所有数据源获取股票列表均失败（新浪财经+东方财富）")
                return None
            
            # 确保必要列存在
            for col in ["code", "name", "price", "pct_change", "volume", "amount"]:
                if col not in df.columns:
                    df[col] = 0 if col != "name" else ""
            
            df = df[~df["name"].str.contains("ST|退", na=False)].reset_index(drop=True)
            cache.set_dataframe("stock_list", key, df)
            return df
        return None

    def get_stock_name(self, code: str) -> str:
        code = normalize_stock_code(code)
        quote = self.get_realtime_quote(code)
        if quote and quote.get("name"):
            return quote["name"]
        return code


# 全局单例
collector = DataCollector()
