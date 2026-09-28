"""
通用工具函数
"""
import json
import os
import time
import hashlib
from datetime import datetime
from typing import Any, Optional


def today_str(fmt: str = "%Y-%m-%d") -> str:
    return datetime.now().strftime(fmt)


def now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.now().strftime(fmt)


_TRADE_DATE_SET = None


def is_trading_day(date=None) -> bool:
    """判断是否为交易日：周一至周五 且 非法定节假日。

    节假日通过 akshare 新浪交易日历校验（进程内只请求一次）；
    取不到日历时保守回退到“周一至周五即交易日”，避免因接口故障漏跑。
    """
    d = date or datetime.now()
    if d.weekday() >= 5:  # 周六周日
        return False
    global _TRADE_DATE_SET
    try:
        if _TRADE_DATE_SET is None:
            import akshare as ak
            df = ak.tool_trade_date_hist_sina()
            _TRADE_DATE_SET = set(df["trade_date"].astype(str).str[:10])
        return d.strftime("%Y-%m-%d") in _TRADE_DATE_SET
    except Exception:
        return True  # 日历接口失败时保守按交易日处理（宁跑勿漏）


def cache_key(*args) -> str:
    """生成缓存键名"""
    raw = "_".join(str(a) for a in args)
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def save_json(data: Any, filepath: str):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def load_json(filepath: str) -> Optional[Any]:
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def retry(max_retries: int = 2, delay: float = 0.5):
    """重试装饰器（优化：减少重试次数和延迟，避免运行超时）"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            for i in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if i == max_retries - 1:
                        raise
                    time.sleep(delay * (i + 1))
            return None
        return wrapper
    return decorator


def normalize_stock_code(code: str) -> str:
    """标准化股票代码：纯数字，6位"""
    code = code.strip().upper()
    # 去掉前缀如 SH/SZ
    for prefix in ["SH", "SZ", "BJ"]:
        if code.startswith(prefix):
            code = code[2:]
    return code


def get_stock_market(code: str) -> str:
    """判断股票所属市场"""
    code = normalize_stock_code(code)
    if code.startswith(("60", "68", "90")):
        return "sh"  # 沪市
    elif code.startswith(("00", "30", "20")):
        return "sz"  # 深市
    elif code.startswith(("43", "83", "87", "88", "92")):
        return "bj"  # 北交所
    return "unknown"
