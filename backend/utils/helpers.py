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


def is_trading_day() -> bool:
    """简易判断是否为交易日（周一至周五，不含节假日判断）"""
    return datetime.now().weekday() < 5


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


def retry(max_retries: int = 3, delay: float = 1.0):
    """重试装饰器"""
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
